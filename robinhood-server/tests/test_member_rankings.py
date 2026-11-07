from fastapi.testclient import TestClient

from robinhood_server.app import create_app


def test_member_rankings_keep_independent_reporting_scopes(ranking_config):
    api = TestClient(create_app(ranking_config))
    response = api.get("/api/v1/member-rankings")
    assert response.status_code == 200
    data = response.json()
    assert data["spending"]["n"] == 2
    assert data["spending"]["total"] == 52000
    assert data["spending"]["rows"][0]["name"] == "가상가"
    assert data["spending"]["scope"]["reportId"] == "ka:2024-22"
    assert data["assets"]["scope"]["start"] == "2025-12-31"
    assert data["assetSource"]["published"] == "2026-03-26"
    assert data["personalIncome"]["available"] is False


def test_each_party_top_ten_is_computed_from_all_asset_records(ranking_config):
    api = TestClient(create_app(ranking_config))
    data = api.get("/api/v1/member-rankings").json()
    group = next(g for g in data["partyAssets"] if g["party"] == "더불어민주당")
    assert group["n"] == 13
    assert group["median"] == 940000
    assert len(group["rows"]) == 10
    assert group["rows"][-1]["name"] == "재산신고인09"
    assert "재산신고인09" not in {row["name"] for row in data["assets"]["rows"]}
    assert [row["rank"] for row in group["rows"]] == list(range(1, 11))
    assert group["rows"][1]["id"] is None
    assert group["rows"][1]["page"] == 2


def test_asset_rankings_keep_zero_and_negative_values_but_exclude_missing(ranking_config):
    api = TestClient(create_app(ranking_config))
    data = api.get("/api/v1/member-rankings").json()
    assert data["assets"]["n"] == 16
    independent = next(g for g in data["partyAssets"] if g["party"] == "무소속")
    assert independent["rows"][0]["value"] == -100
    assert independent["n"] == 1
    assert independent["rows"][0]["ratioToMedian"] is None
    assert "미기재" in data["parties"]


def test_political_income_excludes_carry_transfers_missing_and_other_terms(ranking_config):
    api = TestClient(create_app(ranking_config))
    income = api.get("/api/v1/member-rankings").json()["politicalIncome"]
    assert income["n"] == 3
    assert income["total"] == 307000
    assert [(row["id"], row["value"]) for row in income["rows"]] == [
        ("na-800", 200000), ("na-279", 107000), ("na-801", 0),
    ]
    assert income["scope"]["start"] == "2024-01-01"
    assert "개인 소득과 다릅니다" in income["scope"]["note"]


def test_party_filter_applies_to_each_member_board(ranking_config):
    api = TestClient(create_app(ranking_config))
    data = api.get("/api/v1/member-rankings", params={"party": "국민의힘"}).json()
    for board in [data["spending"], data["assets"], data["politicalIncome"]]:
        assert board["n"] == 1
        assert board["rows"][0]["name"] == "가상가"
    assert [group["party"] for group in data["partyAssets"]] == ["국민의힘"]


def test_missing_asset_and_income_sources_remain_unavailable(client):
    data = client.get("/api/v1/member-rankings").json()
    assert data["assets"]["rows"] == []
    assert data["assets"]["total"] is None
    assert data["partyAssets"] == []
    assert data["politicalIncome"]["n"] == 0
    assert data["politicalIncome"]["total"] is None


def test_unknown_member_ranking_report_is_rejected(client):
    assert client.get("/api/v1/member-rankings?report=unknown").status_code == 400
