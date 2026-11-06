import json
import sqlite3

import pytest
from robinhood_server.fiscal import available_years, basis_of, build_trends


def section(label, first, second):
    return {
        "basis": label,
        "items": [
            {"name": "보건복지부", "amount": first},
            {"name": "교육부", "amount": second},
        ],
    }


@pytest.fixture
def fiscal():
    return {
        "source": {"name": "공식 출처", "url": "https://example.com/fiscal"},
        "actuals": {
            "years": {
                "2023": {"through_month": 12, "total_expenditure": 200},
                "2024": {"through_month": 12, "total_expenditure": 300},
                "2025": {"through_month": 5, "total_expenditure": 80},
            }
        },
        "expenditure_by_ministry": {
            "history": {"2024": section("결산", 100, 200)},
            "budget_years": {
                "2025": section("확정 예산", 40, 60),
                "2026": section("확정 예산", 60, 140),
            },
            "proposal_years": {"2027": section("정부 예산안", 110, 150)},
        },
        "expenditure_by_sector": {
            "years": {
                "2023": section("결산", 50, 150),
                "2024": section("결산", 120, 180),
            }
        },
    }


def trend(data, key):
    return next(row for row in data["series"] if row["id"] == key)


def test_actual_yearly_amount_rate_and_share_changes(fiscal):
    result = build_trends(fiscal, 2024, "actual")
    assert trend(result, "total")["delta"] == 100
    assert trend(result, "total")["rate"] == 0.5
    row = trend(result, "sector:보건복지부")
    assert row["delta"] == 70
    assert row["rate"] == 1.4
    assert row["current"]["share"] == 0.4
    assert row["shareDeltaPp"] == pytest.approx(15)


def test_budget_never_uses_previous_actual_as_budget(fiscal):
    result = build_trends(fiscal, 2025, "budget")
    row = trend(result, "ministry:보건복지부")
    assert [point["year"] for point in row["points"]] == [2025]
    assert row["delta"] is None
    assert row["rate"] is None


def test_proposal_compares_with_previous_confirmed_budget_explicitly(fiscal):
    result = build_trends(fiscal, 2027, "proposal")
    row = trend(result, "total")
    assert [point["basis"] for point in row["points"]] == [
        "budget",
        "budget",
        "proposal",
    ]
    assert row["current"]["amount"] == 260
    assert row["previous"]["amount"] == 200
    assert row["delta"] == 60
    assert row["rate"] == 0.3
    assert "전년도 확정 예산" in result["note"]


def test_partial_year_is_not_compared_to_previous_full_year(fiscal):
    row = trend(build_trends(fiscal, 2025, "actual"), "total")
    assert row["current"]["amount"] is None
    assert row["delta"] is None and row["rate"] is None


def test_missing_year_is_a_gap_and_does_not_become_previous_year(fiscal):
    fiscal["expenditure_by_ministry"]["budget_years"]["2024"] = fiscal[
        "expenditure_by_ministry"
    ]["budget_years"].pop("2025")
    row = trend(build_trends(fiscal, 2026, "budget"), "total")
    assert [p["amount"] for p in row["points"]] == [100, None, 200]
    assert row["delta"] is None


def test_zero_previous_amount_and_changed_names_do_not_invent_growth(fiscal):
    fiscal["expenditure_by_ministry"]["budget_years"]["2025"] = section(
        "확정 예산", 0, 0
    )
    rows = build_trends(fiscal, 2026, "budget")
    assert trend(rows, "total")["delta"] == 200
    assert trend(rows, "total")["rate"] is None
    assert trend(rows, "ministry:보건복지부")["shareDeltaPp"] is None
    fiscal["expenditure_by_ministry"]["budget_years"]["2026"]["items"][0]["name"] = (
        "새로운 부처명"
    )
    row = trend(build_trends(fiscal, 2026, "budget"), "ministry:새로운 부처명")
    assert row["previous"]["amount"] is None and row["delta"] is None


def test_missing_component_makes_share_denominator_unknown(fiscal):
    fiscal["expenditure_by_sector"]["years"]["2024"]["items"][1]["amount"] = None
    row = trend(build_trends(fiscal, 2024, "actual"), "sector:보건복지부")
    assert row["current"]["amount"] == 120
    assert row["current"]["share"] is None


def test_official_sector_code_survives_label_changes(fiscal):
    for year, label in [("2023", "사회복지"), ("2024", "사회 복지")]:
        item = fiscal["expenditure_by_sector"]["years"][year]["items"][0]
        item.update(code="080", name=label)
    row = trend(build_trends(fiscal, 2024, "actual"), "sector:080")
    assert row["name"] == "사회 복지" and row["delta"] == 70


def test_available_years_and_ambiguous_basis(fiscal):
    assert available_years(fiscal) == {
        "actual": [2025, 2024, 2023],
        "budget": [2026, 2025],
        "proposal": [2027],
    }
    assert basis_of("결산/본예산") is None
    assert basis_of("정부 예산안(국회 확정 예산과 별도)") == "proposal"


def test_api_uses_latest_complete_actual_and_collected_budget_years(
    client, config, fiscal
):
    with sqlite3.connect(config.database) as connection:
        connection.execute(
            "UPDATE metadata SET value=? WHERE key='fiscal'", (json.dumps(fiscal),)
        )
    response = client.get("/api/v1/fiscal")
    assert response.status_code == 200
    body = response.json()
    assert body["selectedYear"] == 2024
    assert body["availableYears"]["budget"] == [2026, 2025]
    assert len(body["history"]) == 2
    proposal = client.get("/api/v1/fiscal?basis=proposal").json()
    assert proposal["selectedYear"] == 2027
    assert proposal["trends"]["series"][0]["previous"]["basis"] == "budget"
    assert client.get("/api/v1/fiscal?basis=budget&year=2024").status_code == 404
    assert client.get("/api/v1/fiscal?basis=unknown").status_code == 422
