from contextlib import contextmanager
import json
import sqlite3
from urllib.parse import quote
import psycopg

from .config import Settings
from .postgres import Connection, search_path, session


class DatasetUnavailable(RuntimeError):
    pass


@contextmanager
def connect(target):
    if isinstance(target, Settings) and target.postgres:
        try:
            with session(target) as conn:
                conn.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                conn.execute("SET LOCAL statement_timeout = '30s'")
                conn.execute("SET LOCAL idle_in_transaction_session_timeout = '60s'")
                search_path(conn, target)
                yield Connection(conn)
        except psycopg.Error:
            raise DatasetUnavailable(
                "조회 데이터베이스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
            ) from None
        return
    path = target.database if isinstance(target, Settings) else target
    if not path.is_file():
        raise DatasetUnavailable(
            "조회 자료를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요."
        )
    db = sqlite3.connect(
        f"file:{quote(str(path.resolve()))}?mode=ro",
        uri=True,
        timeout=15,
        check_same_thread=False,
    )
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def records(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


def payload(db, key, default=None):
    row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def escaped_like(value):
    return (
        "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )


def is_postgres(db):
    return getattr(db, "dialect", "") == "postgres"


def array_values(db, expression, path=None):
    if is_postgres(db):
        source = f"{expression}->'{path}'" if path else f"CAST({expression} AS jsonb)"
        return f"jsonb_array_elements_text({source}) AS item(value)"
    return f"json_each({expression},'$.{path}')" if path else f"json_each({expression})"
