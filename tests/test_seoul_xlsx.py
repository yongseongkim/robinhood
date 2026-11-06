from datetime import datetime
from pathlib import Path
import sys

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from parse_seoul import sheets_xlsx  # noqa: E402


def test_formatted_empty_range_does_not_expand_transaction_rows(tmp_path):
    path = tmp_path / "expense.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "사용내역"
    sheet.append(["집행일자", "집행금액"])
    sheet.append([datetime(2026, 9, 2), 123_000])
    sheet["XFD128"].number_format = "#,##0"
    workbook.save(path)
    workbook.close()
    sheets = sheets_xlsx(path)
    assert sheets == [("사용내역", [["집행일자", "집행금액"], [datetime(2026, 9, 2), 123_000]])]
