"""Optional PostgreSQL engine contract test using PGlite over stdin, without TCP."""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import json, re, sqlite3, subprocess, sys, tempfile
from datetime import datetime
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "robinhood-server/src"))
sys.path.insert(0, str(ROOT / "robinhood-server/tests"))
from conftest import config as config_fixture
from fastapi.testclient import TestClient
from robinhood_server.app import create_app
from robinhood_server.postgres import Row, qmarks, TABLES


class Rows:
    def __init__(self, rows):
        self.rows = iter(rows)

    def fetchone(self):
        return next(self.rows, None)

    def __iter__(self):
        return self.rows


class Engine:
    dialect = "postgres"

    def __init__(self):
        self.process = subprocess.Popen(
            ["node", str(ROOT / "robinhood-server/tests/pg_engine_bridge.mjs")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

    def request(self, query, args=(), op="query"):
        self.process.stdin.write(
            json.dumps({"op": op, "sql": query, "args": args}) + "\n"
        )
        self.process.stdin.flush()
        result = json.loads(self.process.stdout.readline())
        if "error" in result:
            raise RuntimeError(str(result) + " query=" + query)
        return result["result"]

    def execute(self, query, args=()):
        i = iter(range(1, len(args) + 1))
        sql = re.sub("%s", lambda _: "$" + str(next(i)), qmarks(query)).replace(
            "%%", "%"
        )
        result = self.request(sql, args)
        for row in result["rows"]:
            for field in result["fields"]:
                name, kind = field["name"], field["dataTypeID"]
                v = row[name]
                if v is not None:
                    if kind in (114, 3802):
                        row[name] = json.dumps(v, ensure_ascii=False)
                    if kind == 1184:
                        row[name] = datetime.fromisoformat(v.replace("Z", "+00:00"))
                    if kind in (20, 1700):
                        row[name] = int(v) if str(v).lstrip("-").isdigit() else float(v)
        return Rows([Row(r) for r in result["rows"]])

    def close(self):
        self.process.stdin.close()
        self.process.wait()


with tempfile.TemporaryDirectory() as d:
    cfg = config_fixture.__wrapped__(Path(d))
    engine = Engine()
    schema = "\n".join(
        p.read_text()
        for p in sorted(
            (ROOT / "robinhood-server/src/robinhood_server/migrations").glob("*.sql")
        )
    )
    engine.request(
        "CREATE SCHEMA robinhood;SET search_path TO robinhood,pg_catalog;" + schema,
        op="exec",
    )
    with sqlite3.connect(cfg.database) as staging:
        for table in TABLES:
            for row in staging.execute("SELECT * FROM " + table):
                engine.execute(
                    "INSERT INTO "
                    + table
                    + " VALUES ("
                    + ",".join("?" for _ in row)
                    + ")",
                    row,
                )

    @contextmanager
    def connection(_):
        yield engine

    pgcfg = replace(cfg, database_url="postgresql://test.invalid/never-connected")
    with patch("robinhood_server.app.connect", connection):
        api = TestClient(create_app(pgcfg))
        paths = [
            "/api/health",
            "/api/v1/meta",
            "/api/v1/members",
            "/api/v1/members?q=김나래",
            "/api/v1/members?party=더불어민주당",
            "/api/v1/members?region=서울%20마포구",
            "/api/v1/subjects/na-279",
            "/api/v1/councils",
            "/api/v1/councils/mapo",
            "/api/v1/rankings?party=더불어민주당",
            "/api/v1/rankings?target=councils&metric=monthly_average",
            "/api/v1/places",
            "/api/v1/transactions",
            "/api/v1/transactions/refund",
            "/api/v1/transactions/local",
            "/api/v1/findings?q=test",
            "/api/v1/transactions/retained",
            "/api/v1/sources",
        ]
        for path in paths:
            response = api.get(path)
            assert response.status_code == 200, (
                path,
                response.status_code,
                response.text,
            )
        page = api.get("/api/v1/members").json()
        assert page["summary"]["amount"] == 12000 and page["total"] == 1, page
        assert api.get("/api/v1/councils/mapo").json()["summary"]["amount"] == 30000
        assert api.get("/api/v1/transactions/local").json()["perPerson"] == 10000
        assert api.get("/api/v1/transactions/refund").json()["pair"]["amount"] == 90000
        print(
            "PostgreSQL 17.5 WASM engine: 18 API paths and funding/refund/aggregate contracts passed"
        )
    from robinhood_server.job_store import write_status, history, get_schedule

    class Raw:
        def execute(self, query, args=()):
            if not isinstance(query, str):
                query = query.as_string(None)
            return engine.execute(query.replace("%s", "?").replace("%%", "%"), args)

    @contextmanager
    def raw_session(*a, **kw):
        engine.request("BEGIN", op="exec")
        try:
            yield Raw()
            engine.request("COMMIT", op="exec")
        except BaseException:
            engine.request("ROLLBACK", op="exec")
            raise

    with patch("robinhood_server.job_store.session", raw_session):
        record = {
            "id": "run-1",
            "state": "succeeded",
            "startedAt": "2026-10-31T00:00:00+00:00",
            "finishedAt": "2026-10-31T00:01:00+00:00",
            "nextRunAt": "2026-11-01T00:01:00+00:00",
        }
        write_status(
            pgcfg, record, schedule={"nextRunAt": record["nextRunAt"], "failures": 0}
        )
        assert history(pgcfg)[0]["state"] == "succeeded"
        assert get_schedule(pgcfg)["failures"] == 0
        record["state"] = "failed"
        write_status(
            pgcfg, record, schedule={"nextRunAt": record["nextRunAt"], "failures": 2}
        )
        assert len(history(pgcfg)) == 1 and history(pgcfg)[0]["state"] == "failed"
        assert get_schedule(pgcfg)["failures"] == 2
    print("PostgreSQL shared job status, history upsert and durable schedule passed")
    from robinhood_server.correction_store import CorrectionStore

    correction = {
        "id": "correction-1",
        "doc_id": "mapo:test",
        "source_sha256": "a" * 64,
        "extraction_sha256": "b" * 64,
        "prompt_version": "test-v1",
        "model": "configured-test-model",
        "state": "complete",
        "created_at": "2026-11-01T00:00:00+00:00",
        "accepted": [],
        "pending": [],
        "issues": [],
    }
    with patch("robinhood_server.correction_store.session", raw_session):
        store = CorrectionStore(pgcfg)
        store.save(correction)
        assert store.get(correction["id"])["state"] == "complete"
        correction["state"] = "needs_review"
        store.save(correction)
        assert store.get(correction["id"])["state"] == "needs_review"
    print("PostgreSQL OCR correction audit JSONB storage and upsert passed")
    engine.request("BEGIN;DELETE FROM transactions;", op="exec")
    try:
        engine.execute("INSERT INTO extras VALUES ('missing',NULL,NULL)")
    except RuntimeError:
        pass
    else:
        raise AssertionError("FK constraint not enforced")
    engine.request("ROLLBACK", op="exec")
    assert engine.execute("SELECT COUNT(*) n FROM transactions").fetchone()["n"] == 8
    print("Foreign keys and failed publication rollback passed")
    engine.close()
