"""OCR 표 복원 도우미 테스트 (Vision 호출 없이 가짜 상자로 검증)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from parse_ocr import header_anchors, parse_date, sanitize_role, split_box, to_amount  # noqa: E402


def box(text, x, y=0.1, w=0.05, h=0.01):
    return {"text": text, "x": x, "y": y, "w": w, "h": h, "conf": 1.0}


def test_split_box_separates_amount_payment_and_border():
    parts = split_box(box("73,000 카드", 0.8, w=0.12))
    assert [p["text"] for p in parts] == ["73,000", "카드"]
    assert parts[0]["x"] < parts[1]["x"]
    assert [p["text"] for p in split_box(box("4| 강변식당", 0.29))] == ["4", "강변식당"]
    assert [p["text"] for p in split_box(box("6 소양강마차", 0.29))] == ["6", "소양강마차"]


def test_header_anchors_handle_merged_spaced_and_misread_headers():
    boxes = [box("연번", 0.05), box("일자", 0.1), box("시간", 0.16), box("잠소", 0.28), box("집 행목적", 0.5, w=0.1),
             box("대상인원 집행금액 결제방법", 0.75, w=0.2)]
    anchors, _ = header_anchors(boxes)
    assert {"date", "time", "merchant_name", "purpose", "attendees", "amount", "payment_method"} <= set(anchors)
    assert anchors["attendees"] < anchors["amount"] < anchors["payment_method"]


def test_amount_and_date_parsing():
    assert to_amount("63.000") == 63000
    assert to_amount("1,234,500원") == 1234500
    assert parse_date("2023-10-04", 2023) == ("2023-10-04", True)
    assert parse_date("01-12.1", 2026) == ("2026-01-12", False)
    assert parse_date("3/2", 2023) == ("2023-03-02", False)


def test_role_cells_never_keep_personal_names():
    known = frozenset({"행정자치위원장", "의장"})
    assert sanitize_role("김원태 위원장 등 9명", known) is None
    assert sanitize_role("김원태위원장", known) is None
    assert sanitize_role("행정자치위원장", known) == "행정자치위원장"
    assert sanitize_role("의장", known) == "의장"


def test_exact_header_is_not_reused_by_fuzzy_match():
    boxes = [box("연번", 0.03), box("사용자", 0.09), box("승인일", 0.18), box("승인시각", 0.26), box("장소", 0.38),
             box("집행목적", 0.53), box("금액", 0.76), box("결제방법", 0.83)]
    anchors, _ = header_anchors(boxes)
    assert "merchant_name" in anchors and "merchant_address" not in anchors
