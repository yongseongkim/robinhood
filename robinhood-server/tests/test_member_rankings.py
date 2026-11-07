from fastapi.testclient import TestClient
import json
import pytest

from robinhood_server.app import create_app
from robinhood_server.index import build_index


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


def test_realestate_rankings_exclude_leases_without_subtracting_debt(
    asset_category_config,
):
    api = TestClient(create_app(asset_category_config))
    data = api.get("/api/v1/member-rankings").json()
    estate = data["assetCategories"][0]
    assert estate["id"] == "realestate"
    assert estate["n"] == 4
    assert estate["total"] == 1300
    assert estate["median"] == 250
    assert [(row["name"], row["value"]) for row in estate["rows"]] == [
        ("가상가", 800), ("정청래", 400), ("재산신고인01", 100), ("0원 재산", 0),
    ]
    assert estate["scope"]["start"] == "2025-12-31"
    assert "전세·임차권을 제외" in estate["scope"]["note"]
    assert "채무는 차감하지 않습니다" in estate["scope"]["note"]
    assert estate["rows"][2]["id"] is None
    assert estate["rows"][2]["page"] == 2


def test_categories_use_their_own_values_and_keep_zero_without_missing_values(
    asset_category_config,
):
    api = TestClient(create_app(asset_category_config))
    data = api.get("/api/v1/member-rankings").json()
    boards = {board["id"]: board for board in data["assetCategories"]}
    securities = boards["securities"]
    assert securities["label"] == "증권(주식 등)"
    assert securities["n"] == 5
    assert securities["median"] == 1000
    assert securities["total"] == 6100
    assert [row["value"] for row in securities["rows"]] == [3000, 2000, 1000, 100, 0]
    assert securities["rows"][0]["name"] == "미수집 재산"
    assert securities["rows"][0]["name"] not in {
        row["name"] for row in data["assets"]["rows"]
    }
    assert boards["deposits"]["n"] == 4
    assert boards["deposits"]["total"] == 900
    assert boards["crypto"]["n"] == 3
    assert boards["crypto"]["median"] == 0
    assert boards["crypto"]["rows"][0]["ratioToMedian"] is None


def test_category_rankings_follow_party_filter_and_ignore_accounting_year(
    asset_category_config,
):
    api = TestClient(create_app(asset_category_config))
    data = api.get(
        "/api/v1/member-rankings", params={"party": "국민의힘", "report": "ka:2023"}
    ).json()
    expected = {"realestate": 800, "securities": 2000, "deposits": 200, "crypto": 0}
    for board in data["assetCategories"]:
        if board["id"] not in expected:
            continue
        assert board["n"] == 1
        assert board["rows"][0]["name"] == "가상가"
        assert board["rows"][0]["value"] == expected[board["id"]]
        assert board["target"] == "assets"
        assert board["scope"]["start"] == "2025-12-31"
    empty = api.get("/api/v1/member-rankings", params={"party": "없는정당"}).json()
    assert all(board["n"] == 0 for board in empty["assetCategories"])


def test_category_missing_data_is_not_invented_as_zero(ranking_config):
    api = TestClient(create_app(ranking_config))
    data = api.get("/api/v1/member-rankings").json()
    assert len(data["assetCategories"]) == 8
    for board in data["assetCategories"]:
        assert board["n"] == 0
        assert board["rows"] == []
        assert board["median"] is None
        assert board["total"] is None


def test_debt_cash_and_separate_property_categories(extended_asset_config):
    data = TestClient(create_app(extended_asset_config)).get("/api/v1/member-rankings").json()
    boards = {board["id"]: board for board in data["assetCategories"]}
    assert [(row["name"], row["value"]) for row in boards["debt"]["rows"]] == [
        ("가상가", 900), ("큰감소", 500), ("정청래", 200), ("0총자산", 50), ("순재산누락", 0),
    ]
    assert boards["cash"]["rows"][0]["name"] == "순재산누락"
    assert boards["cash"]["n"] == 5
    assert boards["land"]["n"] == 3
    assert boards["land"]["rows"][0]["value"] == 200
    assert boards["buildings"]["rows"][0]["name"] == "정청래"
    assert boards["buildings"]["rows"][0]["value"] == 300


def test_annual_increases_and_decreases_keep_sign_and_period(extended_asset_config):
    api = TestClient(create_app(extended_asset_config))
    data = api.get("/api/v1/member-rankings?report=ka:2023").json()["assetChanges"]
    assert data["year"] == 2025
    assert data["increases"]["scope"]["start"] == "2025-01-01"
    assert data["increases"]["scope"]["end"] == "2025-12-31"
    assert "2024년 말 → 2025년 말" in data["increases"]["scope"]["label"]
    assert [row["value"] for row in data["increases"]["rows"]] == [200, 100]
    assert [row["value"] for row in data["decreases"]["rows"]] == [-500, -300]
    assert data["decreases"]["median"] == -400
    assert data["decreases"]["rows"][0]["ratioToMedian"] is None
    filtered = api.get("/api/v1/member-rankings?party=국민의힘").json()["assetChanges"]
    assert filtered["increases"]["n"] == 0
    assert filtered["decreases"]["rows"][0]["name"] == "가상가"
    old = api.get("/api/v1/rankings?target=assets&metric=change").json()
    assert old["scope"]["kind"] == "annual_change"


def test_concentration_uses_gross_assets_not_net_and_does_not_invent_debt(
    extended_asset_config,
):
    data = TestClient(create_app(extended_asset_config)).get("/api/v1/member-rankings").json()
    property_board, securities = data["assetConcentration"]
    assert property_board["n"] == securities["n"] == 3
    assert property_board["total"] is None
    assert securities["total"] is None
    assert property_board["scope"]["unit"] == "ratio"
    assert [row["name"] for row in property_board["rows"]] == ["정청래", "무채무신고", "가상가"]
    assert property_board["rows"][0]["value"] == 0.4
    assert property_board["rows"][0]["amount"] == 400
    assert property_board["rows"][0]["grossAssets"] == 1000
    assert securities["rows"][0]["name"] == "무채무신고"
    assert securities["rows"][0]["value"] == pytest.approx(2 / 3)
    assert securities["median"] == 0.6
    assert {row["name"] for row in securities["rows"]}.isdisjoint({"미확인채무", "0총자산", "순재산누락"})


def test_party_median_ranking_uses_all_members_and_remains_global(extended_asset_config):
    api = TestClient(create_app(extended_asset_config))
    data = api.get("/api/v1/member-rankings").json()["partyWealth"]
    assert [(row["party"], row["median"], row["n"]) for row in data["rows"]] == [
        ("더불어민주당", 450, 2), ("무소속", 300, 1), ("국민의힘", 25, 2), ("미기재", -100, 1),
    ]
    assert [row["rank"] for row in data["rows"]] == [1, 2, 3, 4]
    assert api.get("/api/v1/member-rankings?party=국민의힘").json()["partyWealth"] == data


def test_unknown_disclosure_year_does_not_fabricate_annual_ranking(extended_asset_config):
    path = extended_asset_config.data / "assets.json"
    data = json.loads(path.read_text())
    data["source"].pop("basis")
    path.write_text(json.dumps(data, ensure_ascii=False))
    build_index(extended_asset_config)
    changes = TestClient(create_app(extended_asset_config)).get("/api/v1/member-rankings").json()["assetChanges"]
    assert changes["year"] is None
    assert changes["increases"]["n"] == changes["decreases"]["n"] == 0
