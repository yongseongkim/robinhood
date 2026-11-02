"""OCR review records survive publication; source records are never updated here."""

import json
import sqlite3
import os

from .postgres import search_path, session


class CorrectionStore:
    def __init__(self, config):
        self.config = config

    def _sqlite(self):
        self.config.var.mkdir(parents=True, exist_ok=True)
        path = self.config.var / "ocr-corrections.sqlite3"
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,data TEXT NOT NULL)"
        )
        return conn

    def get(self, identity):
        if self.config.postgres:
            with session(self.config, writer=True) as conn:
                search_path(conn, self.config)
                row = conn.execute(
                    "SELECT data FROM ocr_corrections WHERE id=%s", (identity,)
                ).fetchone()
                return json.loads(row["data"]) if row else None
        path = self.config.var / "ocr-corrections.sqlite3"
        if not path.exists():
            return None
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT data FROM reviews WHERE id=?", (identity,)
            ).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            conn.close()

    def save(self, value):
        data = json.dumps(value, ensure_ascii=False)
        if self.config.postgres:
            with session(self.config, writer=True) as conn:
                search_path(conn, self.config)
                conn.execute(
                    """INSERT INTO ocr_corrections VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT(id) DO UPDATE SET state=excluded.state,created_at=excluded.created_at,data=excluded.data""",
                    (
                        value["id"],
                        value["doc_id"],
                        value["source_sha256"],
                        value["extraction_sha256"],
                        value["prompt_version"],
                        value["model"],
                        value["state"],
                        value["created_at"],
                        data,
                    ),
                )
            return
        conn = self._sqlite()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO reviews VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                    (value["id"], data),
                )
        finally:
            conn.close()
