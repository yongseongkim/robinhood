"""관악구의회 업무추진비 XLSX 파서 → data/staging/gwanak.jsonl

- 헤더 행('연번')과 그 아래 보조 헤더('일자/시간/상호명/주소')를 합쳐 열 이름을 만든 뒤 이름으로 매핑한다.
- '참석자 명단' 파일은 개인 성명이 포함되어 파싱하지 않는다 (참석 인원은 본 집행내역의 '대상인원수' 사용).
- HWP 등 파싱 불가 파일은 보고서에 사유와 함께 남긴다.
"""
import json
import re
import sys
import warnings
from datetime import date, datetime, time, timedelta

import openpyxl

from common import RAW, STAGING, ROOT, clean_text, parse_period, write_jsonl

warnings.filterwarnings("ignore")
COUNCIL = "관악구의회"


def norm(v):
    return re.sub(r"\s+", "", str(v)) if v is not None else ""


def build_columns(top, sub):
    cols, carry = [], ""
    for j in range(len(top)):
        t = norm(top[j])
        if t:
            carry = t
        s = norm(sub[j]) if sub and j < len(sub) else ""
        cols.append((t or carry if s else t, s))
    return cols


def map_columns(cols):
    m = {}
    for j, (t, s) in enumerate(cols):
        key = None
        if t in ("연번", "번호", "순번"):
            key = "row_no"
        elif t in ("비목", "예산과목"):
            key = "budget_item"
        elif "부서" in t:
            key = "department"
        elif t.startswith("사용자") or t in ("집행자", "직위"):
            key = "user_role"
        elif s == "일자" or t in ("일자", "집행일", "집행일자", "사용일자") or (t in ("일시", "집행일시", "사용일시") and not s):
            key = "date"
        elif s == "시간" or t in ("시간", "집행시간", "사용시간"):
            key = "time"
        elif "금액" in t:
            key = "amount"
        elif s == "상호명" or (t in ("집행장소", "사용장소", "장소", "사용처", "상호", "상호명") and not s):
            key = "merchant_name"
        elif s == "주소" or t == "주소":
            key = "merchant_address"
        elif "내역" in t or "목적" in t:
            key = "purpose"
        elif "인원" in t or t == "집행대상":
            key = "attendees"
        elif "결제" in t or "방법" in t:
            key = "payment_method"
        if key and key not in m:
            m[key] = j
    # 구형 서식: '사용일시' 오른쪽의 이름 없는 열이 시간
    if "date" in m and "time" not in m:
        j = m["date"] + 1
        if j < len(cols) and not cols[j][0] and not cols[j][1]:
            m["time"] = j
    return m


def parse_attendees(v):
    """'의장 외 4명' → 5, '사무국장 등 7명' → 7, 12 → 12. 원문 텍스트는 공개하지 않는다."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) or None
    s = str(v)
    m = re.search(r"외\s*(\d+)\s*명", s)
    if m:
        return int(m.group(1)) + 1
    m = re.search(r"(\d+)\s*명", s) or re.fullmatch(r"\s*(\d+)\s*", s)
    return int(m.group(1)) if m else None


def parse_date(v, period):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 30000 < v < 60000:
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = str(v).strip()
    try:
        m = re.match(r"^(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})", s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.match(r"^(\d{1,2})[.\-/월\s]+(\d{1,2})", s)
        if m and period:
            return date(int(period[:4]), int(m.group(1)), int(m.group(2)))
    except ValueError:  # '2024-24-08' 같은 원문 오기
        return "INVALID"
    return None


def parse_time(v):
    if v is None:
        return None
    if isinstance(v, (time, datetime)):
        return f"{v.hour:02d}:{v.minute:02d}"
    if isinstance(v, float) and 0 <= v < 1:
        mins = round(v * 24 * 60)
        return f"{mins // 60:02d}:{mins % 60:02d}"
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})\s*[:시]\s*(\d{2})", s) or re.match(r"^(\d{2})(\d{2})$", s)
    if m and int(m.group(1)) < 24:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def parse_int(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    s = re.sub(r"[,원\s]", "", str(v))
    m = re.match(r"^-?\d+$", s)
    return int(s) if m else None


def infer_budget_item(filename):
    if "공통경비" in filename:
        return "의정운영공통경비"
    if "의장단" in filename:
        return "의회운영업무추진비"
    return None


def parse_file(path, post, att, bad_rows):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        h = next((i for i, r in enumerate(rows[:15]) if r and any(norm(v) in ("연번", "번호", "순번") for v in r)), None)
        if h is None:
            continue
        sub = rows[h + 1] if h + 1 < len(rows) else None
        has_sub = sub is not None and any(norm(v) in ("일자", "시간", "상호명", "주소") for v in sub)
        cols = build_columns(rows[h], sub if has_sub else None)
        cmap = map_columns(cols)
        if "amount" not in cmap or "date" not in cmap:
            continue
        for r in rows[h + (2 if has_sub else 1):]:
            if r is None:
                continue
            g = lambda k: r[cmap[k]] if k in cmap and cmap[k] < len(r) else None
            amount = parse_int(g("amount"))
            d = parse_date(g("date"), post["period"])
            first = norm(r[0]) if r else ""
            if first in ("합계", "계", "소계", "총계"):
                continue
            if d == "INVALID" or (amount is not None and d is None and g("date") is not None):
                bad_rows.append({"row": [str(v) for v in r[:12]], "reason": "날짜 형식 오류"})
                continue
            if amount is None or d is None:
                continue
            budget_item = clean_text(g("budget_item"))
            inferred = False
            if not budget_item:
                budget_item, inferred = infer_budget_item(att["filename"]), True
            repaired = False
            merchant = g("merchant_name")
            if merchant is not None and isinstance(merchant, str) and ("\n" in merchant or "　" in merchant or merchant != merchant.strip()):
                repaired = True
            out.append({
                "source_id": "gwanak",
                "council": COUNCIL,
                "doc_id": "gwanak:" + att["sha256"][:12],
                "doc_title": att["filename"],
                "doc_url": att["url"],
                "post_url": post["post_url"],
                "period": post["period"],
                "row_no": parse_int(g("row_no")),
                "budget_item": budget_item,
                "budget_item_inferred": inferred,
                "department": clean_text(g("department")),
                "user_role": clean_text(g("user_role")),
                "date": d.isoformat(),
                "time": parse_time(g("time")),
                "amount": amount,
                "merchant_name": clean_text(merchant),
                "merchant_address": clean_text(g("merchant_address")),
                "purpose": clean_text(g("purpose")),
                "attendees": parse_attendees(g("attendees")),
                "payment_method": clean_text(g("payment_method")),
                "parse_confidence": "MEDIUM" if repaired else "HIGH",
            })
    return out


def main():
    manifest = json.loads((RAW / "gwanak" / "manifest.json").read_text())
    for post in manifest:
        post["period"] = parse_period(post["post_title"])
    rows, report = [], []
    seen_sha = {}
    # 오래된 게시글부터: 같은 파일이 나중 게시글에 다시 첨부된 경우 최초 게시글에 귀속
    for post in sorted(manifest, key=lambda p: (p["period"] or "", p["posted_date"] or "")):
        for att in post["attachments"]:
            fn = att["filename"]
            entry = {"post_title": post["post_title"], "period": post["period"], "filename": fn, "sha256": att["sha256"]}
            if "명단" in fn:
                entry.update(status="skipped", reason="참석자 명단(개인 성명 포함) — 파싱 대상 아님")
            elif att["sha256"] in seen_sha:
                entry.update(status="skipped", reason=f"동일 파일이 이전 게시글({seen_sha[att['sha256']]})에 이미 첨부됨 — 해당 월 자료가 잘못 첨부되었을 가능성",
                             duplicate_of=seen_sha[att["sha256"]])
            elif not fn.lower().endswith((".xlsx", ".xlsm")):
                entry.update(status="unparsed", reason=f"지원하지 않는 형식({fn.rsplit('.', 1)[-1]}) — 수동 확인 필요")
            else:
                try:
                    bad = []
                    parsed = parse_file(ROOT / att["local_path"], post, att, bad)
                    if bad:
                        entry["rejected_rows"] = bad
                    entry.update(status="parsed" if parsed else "unparsed", rows=len(parsed),
                                 amount_sum=sum(p["amount"] for p in parsed),
                                 reason=None if parsed else "집행내역 표를 찾지 못함")
                    rows.extend(parsed)
                except Exception as e:  # 손상 파일 등
                    entry.update(status="unparsed", reason=f"파싱 오류: {e}")
            seen_sha.setdefault(att["sha256"], post["post_title"])
            report.append(entry)
    write_jsonl(STAGING / "gwanak.jsonl", rows)
    (STAGING / "gwanak_parse_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    st = {}
    for e in report:
        st[e["status"]] = st.get(e["status"], 0) + 1
    print(f"{len(rows)} rows; files: {st}", file=sys.stderr)
    print("date range:", min(r["date"] for r in rows), max(r["date"] for r in rows), file=sys.stderr)


if __name__ == "__main__":
    main()
