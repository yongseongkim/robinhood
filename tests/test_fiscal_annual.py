"""Official annual settlement tables replace incomplete monthly aggregates."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import fiscal_annual
import collect_fiscal


TABLES = [
    '2024 2025\n총수입 594.5 637.4\n총지출 638.0 684.1',
    '2024 2025\n통합재정수지 -43.5 -46.7\n관리재정수지 -104.8 -104.2',
]


def test_annual_settlement_table_totals_and_invalid_structure():
    values = fiscal_annual.parse_tables(TABLES, 2025)
    assert values['total_revenue'] == 637_400_000_000_000
    assert values['total_expenditure'] == 684_100_000_000_000
    assert values['managed_balance'] == -104_200_000_000_000
    with pytest.raises(ValueError, match='incomplete'):
        fiscal_annual.parse_tables(TABLES[:1], 2025)
    with pytest.raises(ValueError, match='year header'):
        fiscal_annual.parse_tables(TABLES, 2026)
    with pytest.raises(ValueError, match='reconcile'):
        fiscal_annual.parse_tables([TABLES[0], TABLES[1].replace('-46.7', '-20.0')], 2025)


def test_annual_settlement_never_keeps_partial_year_breakdowns(tmp_path, monkeypatch):
    monthly = {'TotalIncome': {'2025': [{'OJ_M': '11', 'TOT_RV_AMT': 581.2, 'NTAX_RV_SUM_AMT': 353.6}]}}
    source = {'name': '한국재정정보원', 'url': 'https://www.fis.kr/report', 'sha256': 'verified'}
    monkeypatch.setattr(collect_fiscal, 'load', lambda service: monthly.get(service, {}))
    monkeypatch.setattr(fiscal_annual, 'settlements', lambda: [{
        'year': 2025, 'values': fiscal_annual.parse_tables(TABLES, 2025), 'source': source,
    }])
    monkeypatch.setattr(collect_fiscal, 'NORMALIZED', tmp_path)
    values = collect_fiscal.normalize({})['actuals']['years']['2025']
    assert values['through_month'] == 12
    assert values['total_revenue'] == 637_400_000_000_000
    assert values['national_tax'] is None and values['fund_revenue'] is None
    assert values['source'] == source
