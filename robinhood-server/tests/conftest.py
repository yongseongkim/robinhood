from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient

from robinhood_server.app import create_app
from robinhood_server.config import Settings
from robinhood_server.index import build_index


@pytest.fixture
def config(tmp_path):
    data = tmp_path / "normalized"
    data.mkdir()
    settings = replace(
        Settings(),
        data=data,
        var=tmp_path / "var",
        database=tmp_path / "var/dashboard.sqlite3",
        database_url="",
        job_database_url="",
    )

    def save(name, value):
        (data / name).write_text(json.dumps(value, ensure_ascii=False))

    save(
        "subjects.json",
        [
            {
                "id": "na-279",
                "name": "정청래",
                "type": "LEGISLATOR",
                "org": "국회",
                "terms": {
                    "제22대": {"party": "더불어민주당", "district": "서울 마포구을"}
                },
            },
            {
                "id": "mapo-role",
                "name": "마포구의회 의장",
                "type": "COUNCIL_ROLE",
                "org": "마포구의회",
                "org_source": "mapo",
                "role": "의장",
                "term": "제9대 후반기",
                "holders": [{"name": "백남환", "party": "국민의힘"}],
            },
        ],
    )
    save(
        "merchants.json",
        [
            {
                "id": "b1071638735",
                "name": "가시리",
                "aliases": ["가시리(여의도점)", "가시리 여의도점"],
                "region": "서울 영등포구",
                "bizno": "107-16-38735",
                "bizno_kind": "INDIVIDUAL_BUSINESS",
                "id_confidence": "HIGH",
            }
        ],
    )
    save(
        "documents.json",
        [
            {
                "doc_id": "ka:2024-22",
                "source_id": "ka-money",
                "title": "정치자금 보고분",
                "period": "2024",
                "url": "https://example.com/ka",
            },
            {
                "doc_id": "mapo:test",
                "source_id": "mapo",
                "title": "의회 경비",
                "period": "2024",
                "url": "https://example.com/mapo",
            },
        ],
    )
    save("reversal_pairs.json", {"refund": "cancelled"})
    save(
        "findings.json",
        [
            {
                "id": "test-finding",
                "subjectId": "na-279",
                "fundingType": "POLITICAL_FUND",
                "explanation": "가시리 확인",
                "observed": {
                    "merchantId": "b1071638735",
                    "merchantName": "가시리",
                    "payee": "가시리",
                },
                "evidenceIds": ["retained"],
            }
        ],
    )
    rows = []

    def row(tid, amount, **extra):
        value = dict(
            id=tid,
            subject_id="na-279",
            source_id="ka-money",
            doc_id="ka:2024-22",
            funding_type="POLITICAL_FUND",
            date="2024-05-01",
            amount=amount,
            category="정치활동_식대",
            merchant_id="b1071638735",
            payee_display="가시리",
            payee_type="BUSINESS",
            quality={"flags": []},
        )
        value.update(extra)
        rows.append(value)

    row("retained", 10000, category="간담회_식대")
    row("cancelled", 90000)
    row("refund", -90000)
    row("duplicate", 10000, duplicate_of="retained")
    row("outside", 500000, quality={"flags": ["DATE_OUTSIDE_REPORT_PERIOD"]})
    row(
        "private", 2000, merchant_id=None, payee_type="INDIVIDUAL", payee_display="홍길동"
    )
    row(
        "local",
        30000,
        subject_id="mapo-role",
        source_id="mapo",
        doc_id="mapo:test",
        funding_type="COUNCIL_OPERATION",
        attendees=3,
        time="12:30",
    )
    row(
        "common",
        80000,
        subject_id="mapo-role",
        source_id="mapo",
        doc_id="mapo:test",
        funding_type="COUNCIL_COMMON",
    )
    (data / "expenditures.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    )
    build_index(settings)
    return settings


@pytest.fixture
def client(config):
    with TestClient(create_app(config)) as api:
        yield api
