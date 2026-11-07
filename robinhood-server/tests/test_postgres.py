from dataclasses import replace
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import json
import os
import sqlite3
import uuid

import psycopg
from psycopg import sql
import pytest
from fastapi.testclient import TestClient

from robinhood_server.app import create_app
from robinhood_server.config import Settings
from robinhood_server.db import connect
from robinhood_server.index import build_index
from robinhood_server.jobs import run_due
from robinhood_server.job_store import get_schedule, history
from robinhood_server.postgres import (
    JobAlreadyRunning,
    Row,
    collection_lock,
    migrate,
    normalize,
    publish,
    qmarks,
    search_path,
    session,
)


def test_bind_markers_and_driver_values():
    assert (
        qmarks("SELECT '?' label, ? value, 'it''s 10%' note")
        == "SELECT '?' label, %s value, 'it''s 10%%' note"
    )
    assert normalize(date(2024, 1, 2)) == "2024-01-02"
    assert normalize(Decimal("39320879698")) == 39320879698
    assert normalize(Decimal("1.5")) == 1.5
    row = Row(amount=123, count=2)
    assert row[0] == row["amount"] == 123


def test_postgres_failure_does_not_fall_back_to_local_data(config, monkeypatch):
    @contextmanager
    def unavailable(*args, **kwargs):
        raise psycopg.OperationalError("unavailable database with private details")
        yield

    monkeypatch.setattr("robinhood_server.db.session", unavailable)
    cfg = replace(
        config, database_url="postgresql://private-user:private-password@invalid/db"
    )
    assert "private-password" not in repr(cfg)
    api = TestClient(create_app(cfg))
    assert api.get("/api/health").status_code == 503
    response = api.get("/api/v1/members")
    assert response.status_code == 503
    assert "private" not in response.text


@pytest.mark.parametrize(
    "schema", ["public", "pg_catalog", "information_schema", "bad;drop", "a.b", ""]
)
def test_service_schema_is_isolated(schema):
    with pytest.raises(ValueError):
        replace(Settings(), database_schema=schema)


@pytest.fixture
def pg_schema(config):
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL enables live PostgreSQL integration tests.")
    cfg = replace(
        config,
        database_url=url,
        job_database_url="",
        database_schema="rh_test_" + uuid.uuid4().hex,
    )
    migrate(cfg)
    try:
        yield cfg
    finally:
        # Only a randomly generated test schema is removed; never production schemas.
        with session(cfg, writer=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(cfg.database_schema)
                )
            )


@pytest.fixture
def pg_config(pg_schema):
    migrate(pg_schema, post_deploy=True)
    return pg_schema


def test_source_names_work_before_and_after_post_deploy_cleanup(pg_schema):
    build_index(pg_schema)
    with session(pg_schema, writer=True) as conn:
        search_path(conn, pg_schema)
        conn.execute("UPDATE subjects SET display_name='이전 표시 이름'")
        conn.execute(
            "UPDATE merchants SET display_name='이전 거래처', display_aliases='[]'"
        )
        conn.execute(
            "INSERT INTO metadata VALUES ('people_aliases', %s::jsonb)",
            (json.dumps({"정청래": "이전 표시 이름"}),),
        )
    migrate(pg_schema)
    with connect(pg_schema) as conn:
        assert conn.execute(
            "SELECT display_name FROM subjects WHERE id='na-279'"
        ).fetchone()[0] == "이전 표시 이름"

    api = TestClient(create_app(pg_schema))
    assert api.get("/api/v1/members?q=정청래").json()["rows"][0]["name"] == "정청래"
    assert "pseudonyms" not in api.get("/api/v1/meta").json()
    migrate(pg_schema, post_deploy=True)
    migrate(pg_schema, post_deploy=True)
    with connect(pg_schema) as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=? AND table_name IN ('subjects','merchants')",
                (pg_schema.database_schema,),
            )
        }
        assert not columns & {"display_name", "display_aliases"}
        assert not conn.execute(
            "SELECT 1 FROM metadata WHERE key='people_aliases'"
        ).fetchone()
    assert api.get("/api/health").status_code == 200
    assert api.get("/api/v1/members?q=정청래").json()["total"] == 1
    build_index(pg_schema)
    assert api.get("/api/health").status_code == 200


def test_postgres_api_contract_and_repeatable_reads(pg_config):
    build_index(pg_config)
    with connect(pg_config) as old:
        before = old.execute("SELECT SUM(amount) amount FROM transactions").fetchone()[
            0
        ]
        path = pg_config.data / "expenditures.jsonl"
        path.write_text(
            path.read_text().replace('"amount": 10000', '"amount": 11234', 1)
        )
        build_index(pg_config)
        assert (
            old.execute("SELECT SUM(amount) amount FROM transactions").fetchone()[0]
            == before
        )
    api = TestClient(create_app(pg_config))
    assert api.get("/api/health").status_code == 200
    assert api.get("/api/v1/members").json()["summary"]["amount"] == 13234
    assert api.get("/api/v1/councils/mapo").json()["summary"]["amount"] == 30000
    assert api.get("/api/v1/transactions/local").json()["perPerson"] == 10000
    assert api.get("/api/v1/transactions/refund").json()["pair"]["amount"] == 90000
    for path in [
        "/api/v1/meta",
        "/api/v1/places",
        "/api/v1/subjects/na-279",
        "/api/v1/sources",
        "/api/v1/findings",
    ]:
        assert api.get(path).status_code == 200


def test_member_rankings_match_sqlite_after_postgres_publication(
    pg_config, asset_category_config
):
    build_index(pg_config)
    postgres_api = TestClient(create_app(pg_config))
    sqlite_api = TestClient(create_app(asset_category_config))
    for params in [{}, {"party": "없는정당"}, {"party": "국민의힘"}]:
        response = postgres_api.get("/api/v1/member-rankings", params=params)
        assert response.status_code == 200
        assert response.json() == sqlite_api.get(
            "/api/v1/member-rankings", params=params
        ).json()


def test_postgres_failed_copy_rolls_back(pg_config, config, tmp_path):
    build_index(pg_config)
    # A valid SQLite staging file with a PostgreSQL foreign-key violation forces
    # failure after DELETE has executed, exercising the actual transaction rollback.
    bad = tmp_path / "bad.sqlite3"
    import shutil

    shutil.copyfile(config.database, bad)
    with sqlite3.connect(bad) as conn:
        conn.execute("UPDATE transactions SET subject_id='missing'")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        publish(pg_config, bad)
    with connect(pg_config) as conn:
        assert conn.execute("SELECT COUNT(*) n FROM transactions").fetchone()[0] == 8


def test_postgres_council_findings_preserve_scope_and_subject_integrity(pg_config):
    path = pg_config.data / "findings.json"
    findings = json.loads(path.read_text())
    council_finding = {
        "id": "council-disclosure-gap",
        "ruleId": "DISCLOSURE_GAP",
        "subjectId": "org-mapo",
        "sourceId": "mapo",
        "fundingType": None,
        "observed": {"missingMonths": ["2024-02"]},
        "evidenceIds": [],
    }
    findings.append(council_finding)
    path.write_text(json.dumps(findings))
    build_index(pg_config)
    build_index(pg_config)
    api = TestClient(create_app(pg_config))
    assert api.get("/api/health").status_code == 200
    page = api.get("/api/v1/findings", params={"subjectId": "org-mapo"}).json()
    assert page["total"] == 1
    assert page["rows"][0]["subjectId"] == "org-mapo"
    assert page["rows"][0]["observed"] == council_finding["observed"]
    with connect(pg_config) as conn:
        assert conn.execute(
            "SELECT spending_subject_id FROM findings WHERE id='test-finding'"
        ).fetchone()[0] == "na-279"

    # 의회 scope 예외는 규칙과 출처가 모두 일치할 때만 적용한다.
    for changes in [
        {"ruleId": "OTHER_RULE"},
        {"sourceId": "seoul"},
        {"subjectId": "missing"},
    ]:
        path.write_text(json.dumps([*findings[:-1], {**council_finding, **changes}]))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            build_index(pg_config)
        assert api.get("/api/health").status_code == 200
        assert api.get(
            "/api/v1/findings", params={"subjectId": "org-mapo"}
        ).json()["total"] == 1


def test_postgres_cross_connection_exclusion_and_durable_schedule(pg_config):
    build_index(pg_config)
    with collection_lock(pg_config):
        with pytest.raises(JobAlreadyRunning):
            with collection_lock(pg_config):
                pass
    import subprocess

    runner = lambda command, **kw: subprocess.CompletedProcess(command, 0)
    assert run_due(pg_config, runner=runner)["state"] == "succeeded"
    assert (
        run_due(pg_config, runner=lambda *a, **kw: pytest.fail("duplicate execution"))[
            "state"
        ]
        == "waiting"
    )
    assert get_schedule(pg_config)["nextRunAt"]
    assert history(pg_config)[0]["state"] == "succeeded"
