from dataclasses import replace
import hashlib
import json
import subprocess
import signal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from robinhood_server.app import create_app
from robinhood_server.config import Settings
from robinhood_server.index import build_index, collection_lock, public_merchant_id
from robinhood_server.jobs import collect
from robinhood_server.jobs import run_pipeline
from robinhood_server.db import connect
from robinhood_server.scopes import month_series, period, report_period


def test_periods_and_missing_months():
    assert period("2024-01-01", "2024-12-31", "COUNCIL_OPERATION")["kind"] == "annual"
    assert (
        period("2024-02-01", "2024-02-29", "COUNCIL_OPERATION")["label"]
        == "2024년 2월 합계"
    )
    assert "제22대 보고분" in report_period()["label"]
    assert "2024.05.01" in report_period(start="2024-05-01")["label"]
    with pytest.raises(ValueError):
        report_period(start="2023-01-01")
    with pytest.raises(ValueError):
        period("2024-12-31", "2024-01-01", "COUNCIL_OPERATION")
    months = month_series(
        "2024-01-01", "2024-02-29", [{"month": "2024-02", "amount": 0}]
    )
    assert months[0]["amount"] is None and not months[0]["hasRecords"]
    assert months[1]["amount"] == 0 and months[1]["hasRecords"]


def test_funding_duplicates_refunds_and_aliases(client):
    page = client.get("/api/v1/members").json()
    assert page["summary"]["amount"] == 12000
    assert page["summary"]["count"] == 4
    assert page["summary"]["payments"] == 2
    assert page["rows"][0]["name"] == "김나래"
    assert page["monthly"][0]["amount"] is None
    local = client.get("/api/v1/councils/mapo").json()
    assert local["summary"]["amount"] == 30000
    assert local["summary"]["months"] == 1
    assert local["summary"]["monthlyAverage"] == 30000
    common = client.get("/api/v1/councils/mapo?fundingType=COUNCIL_COMMON").json()
    assert common["summary"]["amount"] == 80000
    tx = client.get("/api/v1/transactions/local").json()
    assert tx["perPerson"] == 10000 and tx["time"] == "12:30"
    private = client.get("/api/v1/transactions/private").json()
    assert private["payee"] == "개인(비공개)" and private["perPerson"] is None
    assert client.get("/api/v1/transactions/refund").json()["pair"]["id"] == "cancelled"


@pytest.mark.parametrize(
    "url,status",
    [
        ("/api/v1/members?page=0", 422),
        ("/api/v1/members?pageSize=101", 422),
        ("/api/v1/members?report=unknown", 400),
        ("/api/v1/members?start=2023-01-01", 400),
        ("/api/v1/members?start=invalid", 422),
        ("/api/v1/places?fundingType=COUNCIL_COMMON", 400),
        ("/api/v1/transactions?fundingType=unknown", 400),
        ("/api/v1/councils/mapo?fundingType=POLITICAL_FUND", 400),
        ("/api/v1/rankings?target=members&metric=change", 400),
        ("/api/v1/findings?fundingType=unknown", 400),
        ("/api/v1/transactions/missing", 404),
        ("/api/v1/subjects/missing", 404),
        ("/api/v1/documents/missing", 404),
        ("/api/v1/councils/missing", 404),
        ("/api/v1/places/missing", 404),
        ("/api/missing", 404),
    ],
)
def test_invalid_requests(client, url, status):
    assert client.get(url).status_code == status


def test_search_is_literal_and_reading_original_names_is_opt_in(client, config):
    assert client.get("/api/v1/members?q=%25").json()["total"] == 0
    original = TestClient(create_app(replace(config, pseudonyms=False)))
    assert original.get("/api/v1/members").json()["rows"][0]["name"] == "정청래"
    observed = client.get("/api/v1/findings").json()["rows"][0]["observed"]
    assert observed["merchantId"] == public_merchant_id("b1071638735")
    assert "가시리" not in json.dumps(observed, ensure_ascii=False)


def test_failed_rebuild_and_collector_keep_published_database(config):
    digest = hashlib.sha256(config.database.read_bytes()).hexdigest()
    with (config.data / "expenditures.jsonl").open("a") as stream:
        stream.write('\n{"invalid JSON')
    with pytest.raises(json.JSONDecodeError):
        build_index(config)
    assert hashlib.sha256(config.database.read_bytes()).hexdigest() == digest
    assert not list(config.database.parent.glob("dashboard-*.sqlite3"))

    def failing_runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1)

    with pytest.raises(RuntimeError):
        collect(config, runner=failing_runner)
    assert json.loads((config.var / "job-status.json").read_text())["state"] == "failed"
    assert hashlib.sha256(config.database.read_bytes()).hexdigest() == digest
    with collection_lock(config.var):
        with pytest.raises(RuntimeError, match="다른 수집"):
            build_index(config)


def test_unindexed_server_reports_unavailable(tmp_path):
    client = TestClient(
        create_app(
            replace(
                Settings(),
                database=tmp_path / "missing.sqlite3",
                database_url="",
                job_database_url="",
            )
        )
    )
    assert client.get("/api/health").status_code == 503
    assert client.get("/api/v1/meta").status_code == 503


def test_successful_publish_keeps_existing_readers_consistent(config):
    with connect(config.database) as reader:
        before = reader.execute("SELECT SUM(amount) FROM transactions").fetchone()[0]
        file = config.data / "expenditures.jsonl"
        rows = [json.loads(line) for line in file.read_text().splitlines()]
        rows[0]["amount"] += 1234
        file.write_text("\n".join(json.dumps(r) for r in rows))
        status = collect(
            config,
            no_fetch=True,
            runner=lambda *a, **kw: subprocess.CompletedProcess(a[0], 0),
        )
        assert status["state"] == "succeeded" and not status["fetch"]
        assert (
            reader.execute("SELECT SUM(amount) FROM transactions").fetchone()[0]
            == before
        )
        with connect(config.database) as new_reader:
            assert (
                new_reader.execute("SELECT SUM(amount) FROM transactions").fetchone()[0]
                == before + 1234
            )


def test_job_timeout_stops_the_crawler_process_group(monkeypatch):
    process = MagicMock()
    process.__enter__.return_value = process
    process.pid = 123
    process.wait.side_effect = [subprocess.TimeoutExpired(["crawler"], 10), 0]
    calls = []
    monkeypatch.setattr(
        "robinhood_server.jobs.subprocess.Popen", lambda *a, **kw: process
    )
    monkeypatch.setattr(
        "robinhood_server.jobs.os.killpg", lambda pid, sig: calls.append((pid, sig))
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_pipeline(["crawler"], timeout=10)
    assert calls == [(123, signal.SIGTERM)]


@pytest.fixture(scope="module")
def real_api():
    config = replace(Settings(), database_url="", job_database_url="")
    if not config.database.is_file():
        pytest.skip("Build the real-data index with robinhood index first.")
    return TestClient(create_app(config))


def test_real_collection_reconciles_with_design_snapshot(real_api):
    page = real_api.get("/api/v1/members").json()
    assert page["total"] == 301
    assert page["summary"]["amount"] == 39320879698
    democratic = real_api.get(
        "/api/v1/rankings", params={"party": "더불어민주당"}
    ).json()
    assert democratic["n"] == 171 and democratic["total"] == 23922562354
    mapo = real_api.get("/api/v1/councils/mapo").json()
    assert mapo["summary"]["amount"] == 107890640 and mapo["summary"]["count"] == 916
    assert mapo["summary"]["months"] == 12
    place = real_api.get("/api/v1/places/" + public_merchant_id("b1071638735")).json()
    assert place["merchant"]["name"] == "여의도밥상"
    assert (
        place["summary"]["payments"] == 424 and place["summary"]["amount"] == 79713893
    )
    assert place["payerCount"] == 132 and place["refunds"] == 7
    assert (
        sum(m["payments"] for m in place["monthly"] if m["month"].startswith("2024"))
        == 203
    )
    local = real_api.get(
        "/api/v1/places/" + public_merchant_id("b1071638735"),
        params={"fundingType": "COUNCIL_OPERATION"},
    ).json()
    assert local["summary"]["amount"] == 166000 and local["summary"]["count"] == 1
    assert (
        real_api.get("/api/v1/places", params={"region": "서울 영등포구"}).json()[
            "total"
        ]
        == 1127
    )


def test_real_transaction_fields_and_stock_vs_flow(real_api):
    tx = real_api.get("/api/v1/transactions/ka22-24_163112").json()
    assert tx["amount"] == 83000 and tx["receiptNo"] == "1"
    assert tx["attendees"] is None and tx["time"] is None and tx["perPerson"] is None
    refund = real_api.get("/api/v1/transactions/ka22-24_163113").json()
    assert refund["amount"] + refund["pair"]["amount"] == 0
    local = real_api.get("/api/v1/transactions/mapo-f0a850f38629-28").json()
    assert local["perPerson"] == 27500 and local["attendees"] == 12
    profile = real_api.get("/api/v1/subjects/na-279").json()
    assert profile["assets"]["total"]["cur"] == 2074349000
    assert profile["assets"]["source"]["basis"] == "2025-12-31"
    for year, basis in [(2024, "actual"), (2026, "budget"), (2027, "proposal")]:
        response = real_api.get("/api/v1/fiscal", params={"year": year, "basis": basis})
        assert response.status_code == 200
        result = response.json()
        assert result["scope"]["start"] == f"{year}-01-01"
        assert result["scope"]["end"] == f"{year}-12-31"
        assert bool(result["values"]) == (basis == "actual")
    assert real_api.get("/api/v1/fiscal?year=2027&basis=actual").status_code == 404


def test_real_findings_pagination_and_geo_precision(real_api):
    first = real_api.get("/api/v1/findings?pageSize=2").json()
    second = real_api.get("/api/v1/findings?pageSize=2&page=2").json()
    assert first["total"] > 2
    assert not {r["id"] for r in first["rows"]} & {r["id"] for r in second["rows"]}
    geo = real_api.get("/api/v1/geo").json()
    assert all("lat" in p and "lng" in p for p in geo["seoul"])
