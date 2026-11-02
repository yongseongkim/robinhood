"""Collection orchestration with shared exclusion, durable schedules and bounded retries."""

from datetime import datetime, timedelta, timezone
import math
import os
import signal
import subprocess
import threading
import sys

from .config import Settings
from .index import build_index, collection_lock
from .job_store import get_schedule, latest, write_status
from .job_store import read_json
from .postgres import JobAlreadyRunning, migrate


def now():
    return datetime.now(timezone.utc)


def run_pipeline(command, *, timeout, **kwargs):
    kwargs.pop("check", None)
    with subprocess.Popen(command, start_new_session=True, **kwargs) as process:
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    return subprocess.CompletedProcess(command, returncode)


def validate_policy(interval_hours, retry_seconds):
    if not math.isfinite(interval_hours) or interval_hours <= 0:
        raise ValueError("작업 간격은 0보다 큰 유한한 시간이어야 합니다.")
    if any(not math.isfinite(v) or v < 1 for v in retry_seconds):
        raise ValueError("재시도 간격은 1초 이상이어야 합니다.")


def collect(
    config: Settings,
    *,
    no_fetch=False,
    timeout=7200,
    runner=run_pipeline,
    locked=False,
    interval_hours=24,
    retry_seconds=(60, 300, 900),
    clock=now,
):
    validate_policy(interval_hours, retry_seconds)
    if not locked:
        with collection_lock(config):
            return collect(
                config,
                no_fetch=no_fetch,
                timeout=timeout,
                runner=runner,
                locked=True,
                interval_hours=interval_hours,
                retry_seconds=retry_seconds,
                clock=clock,
            )
    if config.postgres:
        migrate(config)
    previous = latest(config, writer=True)
    if previous.get("state") == "running":
        # Acquiring the shared lock proves the prior collector is no longer running.
        previous.update(
            state="interrupted",
            finishedAt=clock().isoformat(),
            message="이전 작업이 완료되기 전에 중단되었습니다.",
        )
        write_status(config, previous)
    schedule = get_schedule(config)
    failures = schedule.get("failures", 0)
    stamp = clock().strftime("%Y%m%dT%H%M%S%f")
    logs = config.var / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_name = f"{stamp}.log"
    status = {
        "id": stamp,
        "state": "running",
        "startedAt": clock().isoformat(),
        "fetch": not no_fetch,
        "log": log_name,
        "attempt": failures + 1,
        "published": False,
        "stage": "pipeline",
    }
    write_status(config, status)
    command = ["bash", str(config.root / "pipeline/run_all.sh")]
    if no_fetch:
        command.append("--no-fetch")
    env = {
        **os.environ,
        "ROBIN_HOOD_PIPELINE_PYTHON": config.collector_python,
        "ROBIN_HOOD_SKIP_LEGACY_SITE": "1",
        "ROBIN_HOOD_OCR_CORRECTION_PYTHON": sys.executable,
        "ROBIN_HOOD_OCR_CORRECTIONS": str(config.var / "ocr-corrections.json"),
        "ROBIN_HOOD_VAR": str(config.var),
        "ROBIN_HOOD_DATABASE_URL": config.database_url,
        "DATABASE_URL": config.database_url,
        "ROBIN_HOOD_JOB_DATABASE_URL": config.job_database_url,
        "ROBIN_HOOD_DATABASE_SCHEMA": config.database_schema,
        "ROBIN_HOOD_OCR_CORRECTION_ENABLED": str(config.ocr_correction_enabled).lower(),
        "ROBIN_HOOD_OCR_MODEL": config.ocr_model,
        "ROBIN_HOOD_OCR_EFFORT": config.ocr_effort,
        "ROBIN_HOOD_OCR_CODEX_HOME": config.ocr_codex_home,
        "ROBIN_HOOD_OCR_MAX_BATCHES": str(config.ocr_max_batches),
        "ROBIN_HOOD_OCR_BATCH_ROWS": str(config.ocr_batch_rows),
        "ROBIN_HOOD_OCR_TIMEOUT_SECONDS": str(config.ocr_timeout),
    }
    try:
        fd = os.open(logs / log_name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as log:
            result = runner(
                command,
                cwd=config.root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        if result.returncode:
            raise RuntimeError(f"collector exit {result.returncode}")
        status["ocrCorrection"] = read_json(
            config.var / "ocr-correction-status.json", {"state": "not_run"}
        )
        status["stage"] = "publication"
        write_status(config, status)
        indexed = build_index(config, locked=True)
        status.update(
            state="succeeded",
            finishedAt=clock().isoformat(),
            counted=indexed["counted"],
            published=True,
            stage="complete",
            message="수집과 조회 데이터 발행을 완료했습니다.",
        )
    except BaseException as error:
        failures += 1
        retry = failures <= len(retry_seconds) and isinstance(error, Exception)
        delay = retry_seconds[failures - 1] if retry else interval_hours * 3600
        status.update(
            state="failed",
            finishedAt=clock().isoformat(),
            errorType=type(error).__name__,
            nextRunAt=(clock() + timedelta(seconds=delay)).isoformat(),
            retryScheduled=retry,
            message="수집·적재에 실패했습니다. 이전 조회 데이터를 유지합니다.",
        )
        write_status(
            config,
            status,
            schedule={
                "nextRunAt": status["nextRunAt"],
                "failures": failures if retry else 0,
            },
        )
        raise
    status["nextRunAt"] = (clock() + timedelta(hours=interval_hours)).isoformat()
    # This write is outside the failure handler: a status-write failure must not
    # falsely claim that an already committed publication was rolled back.
    write_status(
        config, status, schedule={"nextRunAt": status["nextRunAt"], "failures": 0}
    )
    return status


def run_due(
    config,
    *,
    interval_hours=24,
    retry_seconds=(60, 300, 900),
    no_fetch=False,
    clock=now,
    runner=run_pipeline,
):
    validate_policy(interval_hours, retry_seconds)
    with collection_lock(config):
        if config.postgres:
            migrate(config)
        schedule = get_schedule(config)
        due = (
            datetime.fromisoformat(schedule["nextRunAt"])
            if schedule.get("nextRunAt")
            else None
        )
        if due and due > clock():
            return {"state": "waiting", "nextRunAt": due.isoformat()}
        return collect(
            config,
            locked=True,
            interval_hours=interval_hours,
            retry_seconds=retry_seconds,
            no_fetch=no_fetch,
            clock=clock,
            runner=runner,
        )


def worker(config: Settings, *, interval_hours=24, no_fetch=False, stop=None):
    validate_policy(interval_hours, ())
    stop = stop or threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        try:
            run_due(config, interval_hours=interval_hours, no_fetch=no_fetch)
        except JobAlreadyRunning:
            pass  # Another host owns the collector; recheck the shared schedule later.
        except Exception as error:
            print(
                f"수집 실패: {type(error).__name__}; 저장된 재시도 시각에 다시 확인합니다.",
                flush=True,
            )
        stop.wait(30)
