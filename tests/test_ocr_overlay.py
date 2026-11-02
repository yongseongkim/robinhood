"""Correction overlays must preserve source records and accounting totals."""

from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from ocr_overlay import apply_rows, fingerprint, row_key


def test_normalization_uses_correction_without_changing_source_or_duplicate_logic(
    tmp_path, monkeypatch
):
    import normalize

    row = {
        "source_id": "mapo",
        "doc_id": "mapo:abc",
        "doc_title": "source.pdf",
        "doc_url": "https://example.com/source.pdf",
        "post_url": "https://example.com/post",
        "period": "2024-01",
        "row_no": 1,
        "date": "2024-01-02",
        "time": "12:30",
        "amount": 130000,
        "attendees": 10,
        "budget_item": "의회운영업무추진비",
        "user_role": "의장",
        "merchant_name": "한빛식당",
        "merchant_address": "서울 마포구",
        "purpose": "지역 주민 간 담회",
        "payment_method": "카드",
        "ocr": True,
        "parse_confidence": "LOW",
    }
    text = json.dumps(row, ensure_ascii=False)
    (tmp_path / "mapo.jsonl").write_text("")
    (tmp_path / "mapo_ocr.jsonl").write_text(text)
    overlay = {
        "version": 1,
        "rows": {
            row_key(row): {
                "review_id": "review-1",
                "row_hash": fingerprint(row),
                "patches": [
                    {
                        "row_no": 1,
                        "field": "purpose",
                        "before": row["purpose"],
                        "after": "지역 주민 간담회",
                        "reason": "띄어쓰기 정리",
                        "evidence": row["purpose"],
                    }
                ],
            }
        },
    }
    path = tmp_path / "corrections.json"
    path.write_text(json.dumps(overlay, ensure_ascii=False))
    monkeypatch.setattr(normalize, "STAGING", tmp_path)
    monkeypatch.setenv("ROBIN_HOOD_OCR_CORRECTIONS", str(path))
    normalized, _, _ = normalize.load_council("mapo")
    assert normalized[0]["description"] == "지역 주민 간담회"
    assert (
        normalized[0]["amount"] == 130000
        and normalized[0]["quality"]["parse_confidence"] == "LOW"
    )
    assert "OCR_TEXT_CORRECTED" in normalized[0]["quality"]["flags"]
    assert (tmp_path / "mapo_ocr.jsonl").read_text() == text
    # Text cleanup cannot turn two originally distinct transactions into duplicates.
    other = deepcopy(normalized[0])
    other["id"] = "other"
    other["doc_id"] = "mapo:def"
    other.pop("_dedupe_original")
    other["description"] = "지역 주민 간담회"
    normalize.mark_cross_document_duplicates([normalized[0], other])
    assert "duplicate_of" not in other


def test_text_column_move_keeps_numbers_and_row_count():
    row = {
        "doc_id": "doc",
        "row_no": 1,
        "merchant_name": "회의 3건",
        "purpose": "빛식당 2층",
        "amount": 10000,
    }
    overlay = {
        "version": 1,
        "rows": {
            row_key(row): {
                "review_id": "x",
                "row_hash": fingerprint(row),
                "patches": [
                    {
                        "row_no": 1,
                        "field": "purpose",
                        "before": "빛식당 2층",
                        "after": "회의 3건",
                        "reason": "열 복구",
                        "evidence": "회의 3건",
                    },
                ],
            }
        },
    }
    # An unpaired move would delete a number and duplicate another: no silent accounting edits.
    import pytest

    with pytest.raises(ValueError):
        apply_rows([row], overlay)
    overlay["rows"][row_key(row)]["patches"].append(
        {
            "row_no": 1,
            "field": "merchant_name",
            "before": "회의 3건",
            "after": "빛식당 2층",
            "reason": "텍스트 열 복구",
            "evidence": "빛식당 2층",
        }
    )
    result = apply_rows([row], overlay)
    assert len(result) == 1 and result[0]["amount"] == 10000
    assert (
        result[0]["merchant_name"] == "빛식당 2층"
        and result[0]["purpose"] == "회의 3건"
    )
