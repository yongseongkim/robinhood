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


def test_linux_ocr_requires_printed_total_and_readable_rows():
    from parse_ocr import tesseract_review_reason

    rows = [{"date": "2023-11-20", "amount": 268600}]
    assert tesseract_review_reason(rows, 268600, "2023-11", {}) is None
    for total, period, stats in [
        (318600, "2023-11", {}), (None, "2023-11", {}), (268600, "2023-12", {}),
        (268600, "2023-11", {"unreadable_date_rows": 1}),
        (268600, "2023-11", {"missing_amount_rows": 1}),
        (268600, "2023-11", {"unrecognized_pages": 1}),
    ]:
        assert tesseract_review_reason(rows, total, period, stats)


def test_linux_ocr_retry_keeps_only_verified_rows_from_same_source(tmp_path, monkeypatch):
    import json
    import parse_ocr

    monkeypatch.setattr(parse_ocr, "ROOT", tmp_path)
    monkeypatch.setattr(parse_ocr, "RAW", tmp_path)
    monkeypatch.setattr(parse_ocr, "STAGING", tmp_path)
    monkeypatch.setattr(parse_ocr, "ENGINE", parse_ocr.TESSERACT)
    monkeypatch.setattr(parse_ocr, "check_engine", lambda: None)
    monkeypatch.setattr(parse_ocr.sys, "argv", ["parse_ocr.py"])
    source = tmp_path / "mapo"
    source.mkdir()
    sha = "010203040506"
    attachment = {"filename": "원장.pdf 다운로드", "local_path": "원장.pdf", "url": "/file", "sha256": sha}
    post = {"post_title": "업무추진비", "period": "2023-11", "post_url": "/original", "attachments": [attachment]}
    manifest = source / "manifest.json"
    manifest.write_text(json.dumps([post]))
    doc_id = "mapo:" + sha
    report_file = {"doc_id": doc_id, "file": "원장.pdf", "period": "2023-11", "status": "unparsed", "reason": "스캔"}
    parse_report = tmp_path / "mapo_parse_report.json"
    parse_report.write_text(json.dumps([report_file]))
    row = dict.fromkeys(["time", "merchant_name", "merchant_address", "purpose", "budget_item", "attendees",
                         "payment_method", "user_role", "department"])
    row.update(date="2023-11-20", amount=318600, parse_confidence="MEDIUM", ocr_min_conf=0.9)
    monkeypatch.setattr(parse_ocr, "parse_pdf", lambda *args: ([dict(row)], 318600))
    stage, report = tmp_path / "mapo_ocr.jsonl", tmp_path / "mapo_ocr_report.json"
    parse_ocr.main()
    original = json.loads(stage.read_text())
    assert (original["amount"], original["doc_id"]) == (318600, doc_id)
    row["amount"] = 268600
    parse_ocr.main()
    assert json.loads(stage.read_text()) == original
    assert "합계" in json.loads(report.read_text())["files"][0]["lastAttempt"]["reason"]

    attachment["sha256"] = "999999999999"
    report_file["doc_id"] = "mapo:" + attachment["sha256"]
    manifest.write_text(json.dumps([post]))
    parse_report.write_text(json.dumps([report_file]))
    parse_ocr.main()
    assert not stage.read_text()
    held = json.loads(report.read_text())["files"][0]
    assert (held["status"], held["printed_total"], held["amount_sum"]) == ("unparsed", 318600, 268600)


def test_printed_total_row_with_split_korean_label_is_not_a_transaction(monkeypatch):
    import parse_ocr

    header = [box("연번", 0.05), box("일자", 0.15), box("사용장소", 0.40), box("집행금액", 0.70)]
    body = [box("총 사 용금액", 0.40, y=0.2), box("52,000", 0.70, y=0.2),
            box("2023-12-07", 0.15, y=0.3), box("식당", 0.40, y=0.3), box("52,000", 0.70, y=0.3)]
    monkeypatch.setattr(parse_ocr, "ocr_pdf", lambda _: {"pages": [{"boxes": header + body}]})
    monkeypatch.setattr(parse_ocr.pdfium, "PdfDocument", lambda _: None)
    stats = {}
    rows, total = parse_ocr.parse_pdf("sample.pdf", "2023-12", stats=stats)
    assert [(r["date"], r["amount"]) for r in rows] == [("2023-12-07", 52000)]
    assert total == 52000
    assert parse_ocr.tesseract_review_reason(rows, total, "2023-12", stats) is None
