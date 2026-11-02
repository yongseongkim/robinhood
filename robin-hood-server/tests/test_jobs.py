from datetime import datetime, timedelta, timezone
import json
import subprocess

import pytest

from robin_hood_server.jobs import collect, run_due, validate_policy
from robin_hood_server.job_store import get_schedule, latest


class Clock:
    def __init__(self):
        self.time = datetime(2026, 10, 31, tzinfo=timezone.utc)

    def __call__(self):
        return self.time

    def advance(self, seconds):
        self.time += timedelta(seconds=seconds)


def test_restart_honors_saved_schedule(config):
    clock = Clock()
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    result = run_due(config, clock=clock, runner=runner, no_fetch=True)
    assert result["state"] == "succeeded" and result["published"]
    assert len(calls) == 1
    # A new invocation/process reads the persisted state instead of collecting again.
    clock.advance(3600)
    assert run_due(config, clock=clock, runner=runner)["state"] == "waiting"
    assert len(calls) == 1
    clock.advance(23 * 3600)
    assert run_due(config, clock=clock, runner=runner)["state"] == "succeeded"
    assert len(calls) == 2


def test_bounded_backoff_and_daily_recovery(config):
    clock = Clock()

    def failure(command, **kwargs):
        return subprocess.CompletedProcess(command, 1)

    for attempt, delay in enumerate([60, 300, 900, 86400], 1):
        with pytest.raises(RuntimeError):
            run_due(config, clock=clock, runner=failure)
        status = latest(config)
        assert status["attempt"] == attempt
        assert status["retryScheduled"] == (attempt <= 3)
        assert datetime.fromisoformat(status["nextRunAt"]) == clock() + timedelta(
            seconds=delay
        )
        assert run_due(config, clock=clock, runner=failure)["state"] == "waiting"
        clock.advance(delay)
    assert get_schedule(config)["failures"] == 0
    result = run_due(
        config,
        clock=clock,
        runner=lambda command, **kw: subprocess.CompletedProcess(command, 0),
    )
    assert result["attempt"] == 1 and result["state"] == "succeeded"


def test_interrupted_run_is_recovered_after_lock_acquisition(config):
    clock = Clock()
    previous = {"id": "old", "state": "running", "startedAt": clock().isoformat()}
    (config.var / "job-status.json").write_text(json.dumps(previous))
    result = collect(
        config,
        clock=clock,
        runner=lambda command, **kw: subprocess.CompletedProcess(command, 0),
    )
    assert result["state"] == "succeeded"


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_invalid_schedule_does_not_start_work(interval):
    with pytest.raises(ValueError):
        validate_policy(interval, ())
