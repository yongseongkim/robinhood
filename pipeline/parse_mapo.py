"""Parse 마포구의회 업무추진비 attachments (PDF text tables, one XLSX) into the staging schema.

Usage: .venv/bin/python -I pipeline/parse_mapo.py
Reads data/raw/mapo/manifest.json, writes data/staging/mapo.jsonl and
data/staging/mapo_parse_report.json.
"""
import json
import re
import sys
from datetime import date, datetime, time
from pathlib import Path

import openpyxl
import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "mapo"
OUT = ROOT / "data" / "staging" / "mapo.jsonl"
REPORT = ROOT / "data" / "staging" / "mapo_parse_report.json"

# Header keyword -> field. Checked in order; the first match wins for a header cell,
# so specific keywords come before generic ones ("집행내역" before "내역").
HEADER_KEYWORDS = [
    ("연번", "row_no"),
    ("번호", "row_no"),
    ("사용자", "user_role"),
    ("집행부서", "department"),
    ("부서", "department"),
    ("시간", "time"),
    ("집행일시", "date"),
    ("일시", "date"),
    ("일자", "date"),
    ("집행금액", "amount"),
    ("집행액", "amount"),
    ("금액", "amount"),
    ("상호", "merchant_name"),
    ("집행처", "merchant_name"),
    ("집행장소", "merchant_name"),
    ("장소", "merchant_name"),
    ("주소", "merchant_address"),
    ("집행목적", "purpose"),
    ("집행내역", "purpose"),
    ("내역", "purpose"),
    ("인원", "attendees"),
    ("결제방법", "payment_method"),
    ("집행방법", "payment_method"),
    ("결제", "payment_method"),
    ("비목", "budget_item"),
]

BUDGET_ALIASES = [
    ("의정운영공통경비", "의정운영공통경비"),
    ("의정공통", "의정운영공통경비"),
    ("의정운영", "의정운영공통경비"),
    ("의회운영", "의회운영업무추진비"),
    ("기관운영", "기관운영업무추진비"),
    ("기관", "기관운영업무추진비"),
    ("시책추진", "시책추진업무추진비"),
    ("시책", "시책추진업무추진비"),
    ("정원가산", "정원가산업무추진비"),
]

DATE_RE = re.compile(r"(20\d{2})\s*[-./년]+\s*(\d{1,2})\s*[-./월]+\s*(\d{1,2})")
SHORT_DATE_RE = re.compile(r"^(\d{1,2})\s*[-./월]+\s*(\d{1,2})")
KOR_DATE_RE = re.compile(r"\d{1,2}\s*월\s*\d{1,2}\s*일")
# Typo seen in the source ("202-03-27"): 3-digit year. Repaired with the disclosure year.
TYPO_YEAR_RE = re.compile(r"^\d{3}\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})")
# A numbered row as it appears in the PDF text layer, used to repair rows whose table
# cells were lost by the table extractor:
#   "40 의회운영위원장 2024-04-22 12:32:36 긴자료코 마포구청점 의회 운영방안 논의 2 29,000 신용카드 의회운영"
TEXT_ROW_RE = re.compile(
    r"^(?P<no>\d+)\s+(?P<role>.*?)\s*"
    r"(?P<date>20\d{2}\s*[-./]+\s*\d{1,2}\s*[-./]+\s*\d{1,2}\.?|\d{1,2}\s*월\s*\d{1,2}\s*일)\s*"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)?\s*(?P<middle>.*?)\s+(?:(?P<att>\d+)\s+)?"
    r"(?P<amount>-?\d{1,3}(?:,\d{3})+|-?\d+)\s+(?P<pay>\S+)(?:\s+(?P<budget>\S+))?$"
)
TIME_RE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})(?:\s*:\s*\d{2})?")
TOTAL_RE = re.compile(r"^(합\s*계|총\s*계|소\s*계|계)$")


def norm_ws(s):
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s).replace("　", " ")).strip()
    return s or None


def map_header(cells):
    """Return {field: column_index} if the row looks like a header, else None."""
    mapping = {}
    for i, c in enumerate(cells):
        key = re.sub(r"\s+", "", c or "")
        if not key:
            continue
        for kw, field in HEADER_KEYWORDS:
            if kw in key:
                # "일시" header that is really date+time is still "date"; time column separate
                if field not in mapping:
                    mapping[field] = i
                break
    hits = len(mapping)
    if hits >= 4 and "amount" in mapping and "date" in mapping:
        return mapping
    return None


def parse_amount(s):
    if s is None:
        return None
    t = str(s).replace(",", "").replace("원", "").replace(" ", "").strip()
    t = t.replace("△", "-").replace("▲", "-")
    if re.fullmatch(r"\(\d+\)", t):
        t = "-" + t[1:-1]
    if re.fullmatch(r"-?\d+(\.0+)?", t):
        return int(float(t))
    return None


def parse_date(s, period):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date().isoformat()
    if isinstance(s, date):
        return s.isoformat()
    t = str(s)
    m = DATE_RE.search(t)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = SHORT_DATE_RE.search(t.strip()) or TYPO_YEAR_RE.search(t.strip())
        if not m or not period:
            return None
        mo, d = map(int, m.groups())
        y = int(period[:4])
        if int(period[5:7]) == 1 and mo == 12:
            y -= 1
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse_time(s):
    if s is None:
        return None
    if isinstance(s, time):
        return f"{s.hour:02d}:{s.minute:02d}"
    if isinstance(s, datetime):
        return f"{s.hour:02d}:{s.minute:02d}"
    m = TIME_RE.search(str(s))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def parse_int(s):
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    m = re.fullmatch(r"(\d+)\s*(명)?", t)
    return int(m.group(1)) if m else None


def canon_budget(s):
    if not s:
        return None
    key = re.sub(r"\s+", "", s)
    for alias, canon in BUDGET_ALIASES:
        if alias in key:
            return canon
    return norm_ws(s)


def infer_budget(filename):
    name = re.sub(r"\s+", "", filename)
    if "의정운영" in name or "공통경비" in name:
        return "의정운영공통경비"
    if "사무국" in name or "시책" in name or "기관" in name:
        return None  # mixed 시책/기관 file with no 비목 column: do not guess
    if "의장" in name or "위원장" in name or "교섭단체" in name or "의회운영" in name:
        return "의회운영업무추진비"
    return None


def cell(row, mapping, field):
    i = mapping.get(field)
    if i is None or i >= len(row):
        return None
    v = row[i]
    return v


def extract_pdf_rows(path):
    """Return ([(page_no, cells)], date strings seen in the text layer, {page_no: text lines})."""
    out, page_lines = [], {}
    date_lines = 0
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            page_lines[pno] = text.split("\n")
            date_lines += len(DATE_RE.findall(text)) + len(KOR_DATE_RE.findall(text))
            for table in page.extract_tables():
                for raw in table:
                    out.append((pno, list(raw)))
    return out, date_lines, page_lines


def repair_from_text(row_no, lines, cells, mapping, ctx):
    """Rebuild a numbered row from the page text when the table extractor dropped cells."""
    for line in lines or []:
        m = TEXT_ROW_RE.match(line.strip())
        if not m or int(m.group("no")) != row_no:
            continue
        purpose_cell = norm_ws(cell(cells, mapping, "purpose"))
        merchant_cell = norm_ws(cell(cells, mapping, "merchant_name"))
        middle = norm_ws(m.group("middle")) or ""
        merchant, purpose = merchant_cell, purpose_cell
        if merchant is None and purpose and middle.endswith(purpose):
            merchant = norm_ws(middle[: -len(purpose)])
        att = parse_int(cell(cells, mapping, "attendees"))
        if att is None and m.group("att"):
            att = int(m.group("att"))
        return {
            "date": parse_date(m.group("date"), ctx["period"]),
            "time": parse_time(m.group("time")),
            "amount": parse_amount(m.group("amount")),
            "merchant_name": merchant,
            "purpose": purpose,
            "attendees": att,
            "payment_method": norm_ws(cell(cells, mapping, "payment_method")) or m.group("pay"),
            "user_role": norm_ws(cell(cells, mapping, "user_role")) or norm_ws(m.group("role")),
            "budget_raw": norm_ws(cell(cells, mapping, "budget_item")) or m.group("budget"),
            "confidence": "MEDIUM" if merchant and purpose else "LOW",
        }
    return None


def split_merged_row(cells, mapping, ctx):
    """A missing horizontal rule makes pdfplumber merge N rows into one with "\n"-joined cells.

    Split cells that have exactly N lines; others go to the first sub-row and are marked as
    needing a fill from the following continuation row.
    """
    di = mapping["date"]
    parts = (cells[di] or "").split("\n") if isinstance(cells[di], str) else []
    dates = [p for p in parts if parse_date(p, ctx["period"])]
    if len(dates) < 2 or len(dates) != len(parts):
        return None
    n = len(parts)
    subrows = [[None] * len(cells) for _ in range(n)]
    needs = [set() for _ in range(n)]
    field_of = {i: f for f, i in mapping.items()}
    for i, c in enumerate(cells):
        lines = c.split("\n") if isinstance(c, str) else [c]
        if len(lines) == n:
            for k in range(n):
                subrows[k][i] = lines[k]
        else:
            subrows[0][i] = c
            for k in range(1, n):
                if i in field_of:
                    needs[k].add(i)
    return [(sub, need, True) for sub, need in zip(subrows, needs)]


def extract_xlsx_rows(path):
    out = []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        for raw in ws.iter_rows(values_only=True):
            out.append((ws.title, list(raw)))
    return out


def build_record(ctx, mapping, cells, d, amt, conf, override=None):
    o = override or {}
    budget_raw = o.get("budget_raw") if "budget_raw" in o else norm_ws(cell(cells, mapping, "budget_item"))
    if budget_raw:
        budget, inferred = canon_budget(budget_raw), False
    else:
        budget, inferred = ctx["budget_inferred"], True
    t_raw = cell(cells, mapping, "time")
    t = o.get("time") if "time" in o else (parse_time(t_raw) if t_raw is not None else None)
    d_raw = cell(cells, mapping, "date")
    if t is None and "time" not in mapping and isinstance(d_raw, str) and len(d_raw) > 10:
        t = parse_time(d_raw[10:])

    def pick(field, parse=norm_ws):
        return o[field] if field in o else parse(cell(cells, mapping, field))

    return {
        "source_id": "mapo",
        "council": "마포구의회",
        "doc_id": ctx["doc_id"],
        "doc_title": ctx["doc_title"],
        "doc_url": ctx["doc_url"],
        "post_url": ctx["post_url"],
        "period": ctx["period"],
        "row_no": parse_int(cell(cells, mapping, "row_no")),
        "budget_item": budget,
        "budget_item_inferred": inferred,
        "department": norm_ws(cell(cells, mapping, "department")),
        "user_role": pick("user_role"),
        "date": d,
        "time": t,
        "amount": amt,
        "merchant_name": pick("merchant_name"),
        "merchant_address": pick("merchant_address"),
        "purpose": pick("purpose"),
        "attendees": pick("attendees", parse_int),
        "payment_method": pick("payment_method"),
        "parse_confidence": conf,
    }


def rows_to_records(raw_rows, ctx):
    """Convert raw table rows (with repeated headers) to records."""
    records, mapping = [], None
    stats = {"totals_printed": [], "continuations": 0, "repaired_from_text": 0, "split_rows": 0}
    skipped = []
    queue = list(raw_rows)
    while queue:
        loc, raw = queue.pop(0)
        if isinstance(raw, tuple):  # split sub-row carrying fields still to be filled
            cells, needs, from_split = raw
        else:
            cells = [c if isinstance(c, (datetime, date, time)) or c is None else str(c) for c in raw]
            needs, from_split = set(), False
        str_cells = [c if isinstance(c, str) else ("" if c is None else str(c)) for c in cells]
        hdr = map_header(str_cells)
        if hdr:
            mapping = hdr
            continue
        if mapping is None or not any(s.strip() for s in str_cells):
            continue
        if not from_split:
            split = split_merged_row(cells, mapping, ctx)
            if split:
                stats["split_rows"] += 1
                queue[0:0] = [(loc, sub) for sub in split]
                continue
        d = parse_date(cell(cells, mapping, "date"), ctx["period"])
        amt = parse_amount(cell(cells, mapping, "amount"))
        row_no = parse_int(cell(cells, mapping, "row_no"))
        if d is not None and amt is not None:
            wrapped = any("\n" in s for s in str_cells)
            merchant = norm_ws(cell(cells, mapping, "merchant_name"))
            conf = "MEDIUM" if (merchant is None or wrapped or from_split) else "HIGH"
            if TYPO_YEAR_RE.search(str(cell(cells, mapping, "date") or "").strip()):
                conf = "MEDIUM"
            rec = build_record(ctx, mapping, cells, d, amt, conf)
            rec["_loc"], rec["_needs"] = loc, needs
            records.append(rec)
            continue
        first_text = re.sub(r"\s+", "", next((s for s in str_cells if s.strip()), ""))
        if TOTAL_RE.match(first_text) or first_text.startswith(("합계", "총계", "소계")):
            if amt is not None:
                stats["totals_printed"].append(amt)
            continue
        if row_no is not None:
            fix = repair_from_text(row_no, ctx["page_lines"].get(loc), cells, mapping, ctx)
            if fix and fix["date"] and fix["amount"] is not None:
                rec = build_record(ctx, mapping, cells, fix.pop("date"), fix.pop("amount"), fix.pop("confidence"), fix)
                rec["_loc"], rec["_needs"] = loc, set()
                records.append(rec)
                stats["repaired_from_text"] += 1
                continue
        if records and d is None and amt is None and row_no is None:
            prev = records[-1]
            if prev["_needs"]:
                # fill the fields a merged-row split could not assign
                fixed = build_record(ctx, mapping, cells, prev["date"], prev["amount"], "MEDIUM")
                for i in prev["_needs"]:
                    field = next(f for f, j in mapping.items() if j == i)
                    if field in fixed and field not in ("date", "amount", "row_no"):
                        prev[field] = fixed[field]
                prev["_needs"] = set()
                prev["parse_confidence"] = "MEDIUM"
            else:
                for f in ("merchant_name", "merchant_address", "purpose"):
                    extra = norm_ws(cell(cells, mapping, f))
                    if extra:
                        prev[f] = norm_ws((prev[f] or "") + " " + extra)
                        prev["parse_confidence"] = "MEDIUM"
            stats["continuations"] += 1
            continue
        skipped.append({"loc": loc, "cells": [norm_ws(s) for s in str_cells]})
    for r in records:
        r.pop("_needs", None)
    return records, stats, skipped


def main():
    manifest = json.loads((RAW_DIR / "manifest.json").read_text(encoding="utf-8"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    report = {"files": [], "unparsed": [], "generated_at": datetime.now().isoformat(timespec="seconds")}
    all_records = []
    seen_sha = {}
    for post in manifest:
        for att in post["attachments"]:
            if att["sha256"] in seen_sha:
                # identical file re-posted on the board: parse once to avoid double counting
                report["duplicates_skipped"] = report.get("duplicates_skipped", []) + [{
                    "file": att["filename"], "post_url": post["post_url"],
                    "same_as_post_url": seen_sha[att["sha256"]],
                }]
                continue
            seen_sha[att["sha256"]] = post["post_url"]
            path = ROOT / att["local_path"]
            ext = path.suffix.lower()
            ctx = {
                "doc_id": "mapo:" + att["sha256"][:12],
                "doc_title": att["filename"],
                "doc_url": att["url"],
                "post_url": post["post_url"],
                "period": post["period"],
                "budget_inferred": infer_budget(att["filename"]),
            }
            entry = {"doc_id": ctx["doc_id"], "file": att["filename"], "period": post["period"]}
            try:
                if ext == ".pdf":
                    raw_rows, date_hits, ctx["page_lines"] = extract_pdf_rows(path)
                elif ext in (".xlsx", ".xlsm"):
                    raw_rows, date_hits = extract_xlsx_rows(path), None
                    ctx["page_lines"] = {}
                else:
                    report["unparsed"].append({**entry, "reason": f"unsupported format {ext}"})
                    continue
            except Exception as e:  # malformed file
                report["unparsed"].append({**entry, "reason": f"read error: {e}"})
                continue
            if ext == ".pdf" and not raw_rows:
                report["unparsed"].append({**entry, "reason": "no extractable table (scanned or text-only PDF)"})
                continue
            recs, stats, skipped = rows_to_records(raw_rows, ctx)
            totals = stats["totals_printed"]
            if not recs:
                report["unparsed"].append({**entry, "reason": "no rows recognised", "skipped_sample": skipped[:5]})
                continue
            off_period = sum(1 for r in recs if post["period"] and r["date"][:7] != post["period"])
            amount_sum = sum(r["amount"] for r in recs)
            entry.update({
                "rows": len(recs),
                "amount_sum": amount_sum,
                "printed_totals": totals,
                "total_matches": (amount_sum in totals) if totals else None,
                "date_strings_in_text": date_hits,
                "continuation_rows_merged": stats["continuations"],
                "rows_repaired_from_text": stats["repaired_from_text"],
                "merged_rows_split": stats["split_rows"],
                "skipped_rows": len(skipped),
                "skipped_sample": skipped[:5],
                "rows_outside_period": off_period,
                "attendees_null": sum(1 for r in recs if r["attendees"] is None),
                "budget_item_inferred": any(r["budget_item_inferred"] for r in recs),
                "confidence": {c: sum(1 for r in recs if r["parse_confidence"] == c) for c in ("HIGH", "MEDIUM", "LOW")},
            })
            report["files"].append(entry)
            all_records.extend(recs)
    with OUT.open("w", encoding="utf-8") as f:
        for r in all_records:
            r.pop("_loc", None)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    report["summary"] = {
        "files_parsed": len(report["files"]),
        "files_unparsed": len(report["unparsed"]),
        "rows": len(all_records),
        "date_min": min(r["date"] for r in all_records),
        "date_max": max(r["date"] for r in all_records),
        "amount_sum": sum(r["amount"] for r in all_records),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
