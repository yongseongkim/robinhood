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


@pytest.fixture
def ranking_config(config):
    subjects_path = config.data / "subjects.json"
    subjects = json.loads(subjects_path.read_text())
    subjects[0]["income"] = {
        "2024": {
            "후원회 기부금": 100000,
            "차입금": 5000,
            "본인 자산": 2000,
            "이월·누계(중복 가능)": 888888,
            "계좌 간 이체(중복 가능)": 999999,
        },
        "2023": {"후원회 기부금": 7777777},
    }
    for sid, name, party, terms, income in [
        ("na-800", "가상가", "국민의힘", "제22대", {"후원회 기부금": 200000}),
        ("na-801", "가상나", "더불어민주당", "제22대", {"본인 자산": 0}),
        ("na-802", "가상다", "국민의힘", "제22대", {}),
        ("na-803", "가상라", "국민의힘", "제21대", {"후원회 기부금": 9999999}),
        ("na-804", "가상마", "국민의힘", "제22대", {"계좌 간 이체(중복 가능)": 999999}),
    ]:
        subjects.append(
            {
                "id": sid,
                "name": name,
                "type": "LEGISLATOR",
                "org": "국회",
                "terms": {terms: {"party": party, "district": "서울 테스트구"}},
                "income": {"2024": income},
            }
        )
    subjects_path.write_text(json.dumps(subjects, ensure_ascii=False))
    path = config.data / "expenditures.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows.append(
        {**rows[0], "id": "other-member", "subject_id": "na-800", "amount": 40000}
    )
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))
    people = [
        {
            "name": "정청래" if i == 0 else f"재산신고인{i:02d}",
            "sid": "na-279" if i == 0 else None,
            "party": "더불어민주당",
            "district": "서울 테스트구",
            "page": i + 1,
            "total": {"cur": 1000000 - i * 10000, "change": 1000},
        }
        for i in range(12)
    ]
    for name, sid, party, value in [
        ("가상가", "na-800", "국민의힘", 3000000),
        ("음수 재산", None, "무소속", -100),
        ("0원 재산", None, "더불어민주당", 0),
        ("미수집 재산", None, "더불어민주당", None),
        ("정당 미기재", None, None, 500),
    ]:
        people.append(
            {
                "name": name,
                "sid": sid,
                "party": party,
                "page": 20,
                "total": {"cur": value, "change": 0},
            }
        )
    (config.data / "assets.json").write_text(
        json.dumps(
            {
                "source": {
                    "title": "테스트 재산공보",
                    "basis": "2025-12-31",
                    "published": "2026-03-26",
                    "url": "https://example.com/assets.pdf",
                },
                "people": people,
            },
            ensure_ascii=False,
        )
    )
    build_index(config)
    return config


@pytest.fixture
def asset_category_config(ranking_config):
    path = ranking_config.data / "assets.json"
    data = json.loads(path.read_text())
    categories = {
        "정청래": {"토지": 100, "건물": 500, "증권": 1000, "예금": 0, "가상자산": 0},
        "재산신고인01": {"건물": 900, "증권": 100, "예금": 700, "가상자산": 30},
        "재산신고인02": {
            "토지": None, "건물": 300, "증권": None, "예금": "350", "가상자산": False,
        },
        "재산신고인03": {"건물": 100},
        "재산신고인04": {"건물": 100},
        "재산신고인05": {"건물": 100},
        "재산신고인06": {"건물": 100},
        "가상가": {
            "토지": 700, "건물": 100, "증권": 2000, "예금": 200, "가상자산": 0,
        },
        "0원 재산": {"건물": 20000, "증권": 0, "예금": 0},
        "미수집 재산": {"증권": 3000, "예금": None, "가상자산": True},
    }
    estates = {
        "정청래": [{"lease": False, "cur": 400}, {"lease": True, "cur": 200}],
        "재산신고인01": [{"lease": False, "cur": 100}, {"lease": True, "cur": 800}],
        "재산신고인02": [{"lease": False, "cur": 300}],
        "재산신고인04": [{"lease": True, "cur": None}],
        "재산신고인05": [{"cur": 100}],
        "재산신고인06": [{"lease": True, "cur": 200}],
        "가상가": [{"lease": False, "cur": 800}],
        "0원 재산": [{"lease": True, "cur": 20000}],
    }
    for person in data["people"]:
        name = person["name"]
        if name in categories:
            person["cats"] = {
                key: {"cur": value} for key, value in categories[name].items()
            }
        if name in estates:
            person["realestate"] = estates[name]
    path.write_text(json.dumps(data, ensure_ascii=False))
    build_index(ranking_config)
    return ranking_config


@pytest.fixture
def extended_asset_config(ranking_config):
    path = ranking_config.data / "assets.json"
    data = json.loads(path.read_text())
    data["people"] = []
    for name, sid, party, net, change, cats, estate, checked in [
        ("정청래", "na-279", "더불어민주당", 800, 100,
         {"토지": 100, "건물": 500, "증권": 100, "예금": 300, "채무": 200, "현금": 0},
         [("토지", 100, False), ("건물", 300, False), ("건물", 200, True)], True),
        ("가상가", "na-800", "국민의힘", 100, -300,
         {"토지": 200, "건물": 0, "증권": 600, "예금": 160, "채무": 900, "현금": 40},
         [("토지", 200, False)], True),
        ("무채무신고", None, "무소속", 300, 200,
         {"건물": 100, "증권": 200, "현금": 0}, [("건물", 100, False)], True),
        ("미확인채무", None, "더불어민주당", 100, None,
         {"건물": 50, "증권": 30, "채무": None, "현금": None}, [("건물", 50, False)], False),
        ("0총자산", None, "국민의힘", -50, 0,
         {"토지": 0, "건물": 0, "증권": 0, "현금": 0, "채무": 50}, [], True),
        ("순재산누락", None, "무소속", None, None,
         {"증권": 500, "채무": 0, "현금": 50}, [], False),
        ("큰감소", None, None, -100, -500,
         {"예금": 400, "채무": 500}, [], True),
    ]:
        data["people"].append({
            "name": name, "sid": sid, "party": party, "page": len(data["people"]) + 1,
            "total": {"cur": net, "change": change,
                      "prev": net - change if net is not None and change is not None else None},
            "cats": {key: {"cur": value} for key, value in cats.items()},
            "realestate": [{"cat": cat, "cur": cur, "lease": lease} for cat, cur, lease in estate],
            "checked": checked,
        })
    path.write_text(json.dumps(data, ensure_ascii=False))
    build_index(ranking_config)
    return ranking_config
