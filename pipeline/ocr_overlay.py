"""Apply separately stored OCR text corrections without rewriting source/staging files."""

from collections import Counter
from copy import deepcopy
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

EDITABLE_FIELDS = {"merchant_name", "purpose", "payment_method"}
PROTECTED_FIELDS = {
    "amount",
    "date",
    "time",
    "attendees",
    "budget_item",
    "user_role",
    "department",
    "merchant_address",
}
FIELDS = EDITABLE_FIELDS | PROTECTED_FIELDS
PAYMENTS = {
    "카드",
    "신용카드",
    "체크카드",
    "법인카드",
    "현금",
    "계좌이체",
    "제로페이",
    "지역화폐",
    "이체",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(row):
    return hashlib.sha256(canonical(row).encode()).hexdigest()


def row_key(row):
    return f"{row['doc_id']}:{row['row_no']}"


def compact(value):
    return re.sub(r"\W", "", unicodedata.normalize("NFKC", value or ""))


def row_text(row):
    return "\n".join(str(row.get(k)) for k in sorted(FIELDS) if row.get(k) is not None)


def validate_proposals(rows, result):
    """Accept bounded text corrections; preserve amounts, dates, identities and row count."""
    if not isinstance(result, dict) or set(result) != {"patches", "issues"}:
        raise ValueError("정정 결과에는 patches와 issues가 필요합니다.")
    if not isinstance(result["patches"], list) or not isinstance(
        result["issues"], list
    ):
        raise ValueError("정정 제안과 미해결 항목은 목록이어야 합니다.")
    if (
        len(result["patches"]) > len(rows) * len(FIELDS)
        or len(result["issues"]) > len(rows) + 1
    ):
        raise ValueError("정정 제안 수가 입력 범위를 벗어났습니다.")
    lookup = {r["row_no"]: r for r in rows}
    if len(lookup) != len(rows):
        raise ValueError("OCR 행 식별자가 중복되었습니다.")
    accepted, pending, seen = [], [], set()
    known_merchants = {
        compact(r.get("merchant_name")) for r in rows if r.get("merchant_name")
    }
    for patch in result["patches"]:
        if not isinstance(patch, dict) or set(patch) != {
            "row_no",
            "field",
            "before",
            "after",
            "reason",
            "evidence",
        }:
            raise ValueError("정정 제안 형식이 올바르지 않습니다.")
        number, field = patch["row_no"], patch["field"]
        if type(number) is not int or number not in lookup or field not in FIELDS:
            raise ValueError("정정 대상 행·항목을 찾을 수 없습니다.")
        if (number, field) in seen:
            raise ValueError("동일한 항목의 중복 정정입니다.")
        seen.add((number, field))
        if not all(
            isinstance(patch[k], str) and 0 < len(patch[k]) <= 2000
            for k in ["reason", "evidence"]
        ):
            raise ValueError("정정 사유와 OCR 텍스트 근거가 필요합니다.")
        if any(
            v is not None
            and (type(v) not in (str, int) or isinstance(v, str) and len(v) > 4000)
            for v in [patch["before"], patch["after"]]
        ):
            raise ValueError("정정 값의 형식·길이가 올바르지 않습니다.")
        row, reason = lookup[number], None
        before, after = patch["before"], patch["after"]
        if field in PROTECTED_FIELDS:
            reason = "수치·기간·재원·주체·주소 항목은 자동 변경하지 않습니다."
        elif type(before) is not type(row.get(field)) or before != row.get(field):
            reason = "수정 전 값이 추출본과 다릅니다."
        elif not isinstance(after, str) or not after.strip():
            reason = "빈 값이나 항목 삭제는 자동 반영하지 않습니다."
        elif patch["evidence"] not in row_text(row):
            reason = "근거 문구가 해당 행의 OCR 추출 텍스트에 없습니다."
        elif not before and after not in row_text(row):
            reason = "빈 칸을 근거 없이 채우지 않습니다."
        elif (
            field == "merchant_name"
            and compact(after) not in known_merchants
            and after not in row_text(row)
        ):
            reason = "표에서 확인되지 않는 거래처 이름입니다."
        elif field == "payment_method" and after not in PAYMENTS:
            reason = "확인되지 않은 결제수단입니다."
        elif (
            field == "purpose"
            and after not in row_text(row)
            and SequenceMatcher(None, before or "", after).ratio() < 0.72
        ):
            reason = "문구 정정을 넘어 내용이 크게 바뀌었습니다."
        if reason:
            pending.append({**patch, "validation": reason})
        elif after != before:
            accepted.append(patch)
    # A text-column move may move digits, but cannot introduce/remove/change them.
    for number, row in lookup.items():
        changes = [p for p in accepted if p["row_no"] == number]
        revised = {**row, **{p["field"]: p["after"] for p in changes}}
        if Counter(re.findall(r"\d+", row_text(row))) != Counter(
            re.findall(r"\d+", row_text(revised))
        ):
            accepted = [p for p in accepted if p["row_no"] != number]
            pending.extend(
                {**p, "validation": "텍스트 안의 숫자 구성이 바뀌었습니다."}
                for p in changes
            )
    for issue in result["issues"]:
        if (
            not isinstance(issue, dict)
            or set(issue) != {"row_no", "reason"}
            or type(issue["row_no"]) is not int
            or issue["row_no"] not in {0, *lookup}
            or not isinstance(issue["reason"], str)
            or not 0 < len(issue["reason"]) <= 2000
        ):
            raise ValueError("미해결 항목 형식이 올바르지 않습니다.")
    return {"accepted": accepted, "pending": pending, "issues": result["issues"]}


def apply_rows(rows, overlay):
    if overlay.get("version") != 1 or not isinstance(overlay.get("rows"), dict):
        raise ValueError("OCR 정정본 버전을 확인해 주세요.")
    grouped = {}
    for row in rows:
        grouped.setdefault(row["doc_id"], []).append(row)
    result = []
    for row in rows:
        item = overlay["rows"].get(row_key(row))
        if not item or item["row_hash"] != fingerprint(row):
            result.append(deepcopy(row))
            continue
        patches = item["patches"]
        checked = validate_proposals(
            grouped[row["doc_id"]], {"patches": patches, "issues": []}
        )
        if checked["pending"]:
            raise ValueError("검증되지 않은 OCR 정정본입니다.")
        if any(
            p["field"] not in EDITABLE_FIELDS or p["before"] != row.get(p["field"])
            for p in patches
        ):
            raise ValueError("OCR 정정본이 보호된 항목을 변경하려 합니다.")
        changed = deepcopy(row)
        changed.update({p["field"]: p["after"] for p in patches})
        if Counter(re.findall(r"\d+", row_text(row))) != Counter(
            re.findall(r"\d+", row_text(changed))
        ):
            raise ValueError("OCR 정정본의 숫자 구성이 바뀌었습니다.")
        changed["_ocr_correction"] = {
            "review_id": item["review_id"],
            "fields": [p["field"] for p in patches],
        }
        changed["_ocr_original_text"] = {
            "merchant_name": row.get("merchant_name"),
            "purpose": row.get("purpose"),
        }
        result.append(changed)
    return result


def load_rows(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    overlay_path = os.getenv("ROBIN_HOOD_OCR_CORRECTIONS", "")
    if not overlay_path:
        return rows
    overlay = Path(overlay_path)
    if not overlay.exists():
        return rows
    return apply_rows(rows, json.loads(overlay.read_text()))
