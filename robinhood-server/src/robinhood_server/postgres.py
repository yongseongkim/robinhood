"""PostgreSQL storage, atomic bulk publication and cross-host job exclusion."""

from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
import hashlib
from pathlib import Path
import sqlite3

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import set_json_loads


TABLES = (
    "subjects",
    "merchants",
    "documents",
    "extras",
    "transactions",
    "findings",
    "metadata",
)
DELETE_ORDER = (
    "findings",
    "transactions",
    "extras",
    "subjects",
    "merchants",
    "documents",
    "metadata",
)
_lease = ContextVar("robinhood_job_lease", default=None)


class JobAlreadyRunning(RuntimeError):
    pass


def lock_key(schema):
    return int.from_bytes(
        hashlib.sha256(("robinhood:collection:" + schema).encode()).digest()[:8],
        "big",
        signed=True,
    )


@contextmanager
def session(config, *, writer=False, autocommit=False):
    url = (
        (config.job_database_url or config.database_url)
        if writer
        else config.database_url
    )
    with psycopg.connect(
        url,
        connect_timeout=10,
        application_name="robinhood-job" if writer else "robinhood-api",
        autocommit=autocommit,
        row_factory=dict_row,
    ) as conn:
        # Existing serializers deliberately return a whitelist from JSON documents.
        set_json_loads(
            lambda value: bytes(value).decode()
            if not isinstance(value, str)
            else value,
            conn,
        )
        yield conn


def search_path(conn, config, *, local=True):
    conn.execute(
        sql.SQL("SET {}search_path TO {}, pg_catalog").format(
            sql.SQL("LOCAL " if local else ""), sql.Identifier(config.database_schema)
        )
    )


def migrate(config):
    with session(config, writer=True) as conn:
        # Serialize migrations separately; do not acquire this lock from API requests.
        conn.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (lock_key(config.database_schema + ":migrations"),),
        )
        conn.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(config.database_schema)
            )
        )
        search_path(conn, config)
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        applied = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations")
        }
        for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version not in applied:
                conn.execute(path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)", (version,)
                )


@contextmanager
def collection_lock(config):
    # Must use a direct/session-pooled connection, not transaction-pooled PgBouncer.
    with session(config, writer=True, autocommit=True) as conn:
        key = lock_key(config.database_schema)
        acquired = conn.execute(
            "SELECT pg_try_advisory_lock(%s) acquired", (key,)
        ).fetchone()["acquired"]
        if not acquired:
            raise JobAlreadyRunning("다른 수집·인덱스 작업이 실행 중입니다.")
        token = _lease.set(
            (
                config.database_schema,
                config.job_database_url or config.database_url,
                conn,
            )
        )
        try:
            yield
        finally:
            _lease.reset(token)
            if not conn.closed:
                try:
                    conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
                except psycopg.Error:
                    pass  # A disconnected session has already lost its locks.


def publish(config, source):
    """COPY a validated scratch index in one transaction. Readers keep their snapshot."""
    lease = _lease.get()
    if lease is None:
        with collection_lock(config):
            return publish(config, source)
    if lease[:2] != (
        config.database_schema,
        config.job_database_url or config.database_url,
    ):
        raise RuntimeError("수집 잠금과 발행 대상 스키마가 다릅니다.")
    migrate(config)
    conn = lease[2]
    # Publish through the exact session that holds the advisory lock. If the
    # lease connection died, publication fails rather than reconnecting unfenced.
    with (
        closing(
            sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        ) as staged,
        conn.transaction(),
    ):
        search_path(conn, config)
        conn.execute("SET LOCAL lock_timeout = '10s'")
        conn.execute("SET LOCAL statement_timeout = '30min'")
        # DELETE is MVCC-safe for old readers; TRUNCATE is deliberately not used.
        for table in DELETE_ORDER:
            conn.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
        counts = {}
        for table in TABLES:
            columns = [row[1] for row in staged.execute(f"PRAGMA table_info({table})")]
            query = sql.SQL("COPY {} ({}) FROM STDIN").format(
                sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns))
            )
            total = 0
            with conn.cursor().copy(query) as copy:
                for row in staged.execute(f"SELECT * FROM {table}"):
                    copy.write_row(row)
                    total += 1
            loaded = conn.execute(
                sql.SQL("SELECT COUNT(*) n FROM {}").format(sql.Identifier(table))
            ).fetchone()["n"]
            if loaded != total:
                raise ValueError(f"PostgreSQL 적재 건수 불일치: {table}")
            counts[table] = total
        if not counts["transactions"]:
            raise ValueError("빈 거래 자료는 발행하지 않습니다.")
    return counts


def qmarks(query):
    """Translate repository bind markers; preserve question marks inside SQL literals."""
    result, quoted, i = [], None, 0
    while i < len(query):
        char = query[i]
        if quoted:
            result.append("%%" if char == "%" else char)
            if char == quoted:
                if i + 1 < len(query) and query[i + 1] == quoted:
                    result.append(query[i + 1])
                    i += 1
                else:
                    quoted = None
        elif char in ("'", '"'):
            quoted = char
            result.append(char)
        elif char == "?":
            result.append("%s")
        else:
            result.append("%%" if char == "%" else char)
        i += 1
    return "".join(result)


class Row(dict):
    def __getitem__(self, key):
        return (
            super().__getitem__(key)
            if not isinstance(key, int)
            else list(self.values())[key]
        )


def normalize(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class Result:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        row = self.cursor.fetchone()
        return (
            Row((k, normalize(v)) for k, v in row.items()) if row is not None else None
        )

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row


class Connection:
    dialect = "postgres"

    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, args=()):
        return Result(self.conn.execute(qmarks(query), args))
