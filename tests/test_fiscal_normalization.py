import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import collect_fiscal


def test_keeps_each_budget_and_proposal_year_with_sector_totals(tmp_path, monkeypatch):
    def row(name, confirmed, proposed):
        return {
            "OFFC_NM": name,
            "FLD_CD": "080",
            "FLD_NM": "사회복지",
            "SACTV_NM": "돌봄",
            "PGM_NM": "복지",
            "Y_YY_DFN_MEDI_KCUR_AMT": confirmed,
            "Y_YY_MEDI_KCUR_AMT": proposed,
        }

    raw = {
        "2025": [row("보건복지부", 100, 90)],
        "2026": [row("보건복지부", 150, 140), row("교육부", 50, 45)],
        "2027": [row("보건복지부", 0, 210), row("교육부", 0, 60)],
    }
    monkeypatch.setattr(
        collect_fiscal,
        "load",
        lambda service: raw if service == "TotalExpenditure5" else {},
    )
    monkeypatch.setattr(collect_fiscal, "NORMALIZED", tmp_path)
    result = collect_fiscal.normalize({})
    ministry = result["expenditure_by_ministry"]
    assert set(ministry["budget_years"]) == {"2025", "2026"}
    assert ministry["year"] == "2026" and ministry["proposal"]["year"] == "2027"
    assert ministry["budget_years"]["2025"]["items"][0]["amount"] == 100_000
    sectors = result["expenditure_by_sector"]
    assert sectors["budget_years"]["2026"]["items"] == [
        {"code": "080", "name": "사회복지", "amount": 200_000}
    ]
    assert sectors["proposal_years"]["2027"]["items"][0]["amount"] == 270_000
    assert (tmp_path / "fiscal.json").is_file()
