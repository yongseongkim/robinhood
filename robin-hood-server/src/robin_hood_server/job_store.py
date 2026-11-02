"""Shared PostgreSQL run history and restart-safe scheduling; local JSON for offline use."""

import json
import os
import tempfile

from .postgres import search_path, session


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.stem + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output, ensure_ascii=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return fallback


def write_status(config, value, *, schedule=None):
    if config.postgres:
        with session(config, writer=True) as conn:
            search_path(conn, config)
            conn.execute(
                """INSERT INTO job_runs(id,state,started_at,finished_at,next_run_at,data)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(id) DO UPDATE SET
                state=excluded.state,finished_at=excluded.finished_at,next_run_at=excluded.next_run_at,data=excluded.data""",
                (
                    value["id"],
                    value["state"],
                    value["startedAt"],
                    value.get("finishedAt"),
                    value.get("nextRunAt"),
                    json.dumps(value, ensure_ascii=False),
                ),
            )
            if schedule:
                conn.execute(
                    """INSERT INTO job_schedule(name,next_run_at,failures) VALUES ('collection',%s,%s)
                    ON CONFLICT(name) DO UPDATE SET next_run_at=excluded.next_run_at,failures=excluded.failures""",
                    (schedule["nextRunAt"], schedule["failures"]),
                )
        return
    atomic_json(config.var / "job-status.json", value)
    if schedule:
        atomic_json(config.var / "job-schedule.json", schedule)


def history(config, limit=20, *, writer=False):
    if config.postgres:
        with session(config, writer=writer) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            search_path(conn, config)
            rows = conn.execute(
                "SELECT data FROM job_runs ORDER BY started_at DESC,id DESC LIMIT %s",
                (limit,),
            )
            return [json.loads(row["data"]) for row in rows]
    value = read_json(config.var / "job-status.json", {})
    return [value] if value else []


def latest(config, *, writer=False):
    rows = history(config, 1, writer=writer)
    return (
        rows[0]
        if rows
        else {"state": "never", "message": "수집 작업 실행 기록이 없습니다."}
    )


def get_schedule(config):
    if config.postgres:
        with session(config, writer=True) as conn:
            search_path(conn, config)
            row = conn.execute(
                "SELECT next_run_at,failures FROM job_schedule WHERE name='collection'"
            ).fetchone()
            return (
                {
                    "nextRunAt": row["next_run_at"].isoformat(),
                    "failures": row["failures"],
                }
                if row
                else {}
            )
    return read_json(config.var / "job-schedule.json", {})
