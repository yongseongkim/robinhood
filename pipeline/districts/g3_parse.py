"""G3 자치구의회 첨부(PDF·XLSX·XLS) → data/staging/<slug>.jsonl

- 헤더 이름으로 열을 매핑한다(의회·연도마다 서식이 다름).
- '사용자' 칸이 세로 병합되어 빈 칸이면 바로 위 행의 사용자를 이어 쓴다.
- 사용자 칸에 개인 성명이 있으면 직책 부분만 남긴다. 사용자 칸이 없으면 파일명·게시글 제목에서 직책을 정한다.
- 참석자 명단 파일은 개인 성명이 있어 파싱하지 않는다.
"""
import json
import re
import sys
import warnings
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE))

import pdfplumber  # noqa: E402

from common import period_range  # noqa: E402
from parse_seoul import (canon_budget, canon_payment, norm, parse_amount, parse_attendees, parse_date,  # noqa: E402
                         parse_time, pdf_is_image_text, pdf_says_empty, sheets_xlsx, split_merchant, squash)

warnings.filterwarnings("ignore")
ROOT = PIPELINE.parent
STAGING = ROOT / "data" / "staging"

# (키워드, 필드) — 앞 규칙 우선
HEADER_KEYWORDS = [
    ("연번", "row_no"), ("번호", "row_no"), ("순번", "row_no"),
    ("인원", "attendees"), ("집행대상", "attendees"), ("대상", "attendees"),
    ("사용자", "user_role"), ("집행자", "user_role"), ("직위", "user_role"),
    ("위원회명", "department"), ("부서", "department"),
    ("비목", "budget_item"), ("과목", "budget_item"), ("구분", "budget_item"),
    ("시간", "time"), ("시각", "time"),
    ("집행일시", "date"), ("사용일시", "date"), ("일시", "date"), ("집행일", "date"), ("사용일", "date"), ("승인일", "date"), ("일자", "date"), ("날짜", "date"),
    ("금액", "amount"),
    ("주소", "merchant_address"), ("소재지", "merchant_address"),  # '가맹점주소'가 상호로 잡히지 않도록 먼저 본다
    ("가맹점", "merchant_name"), ("상호", "merchant_name"), ("거래처", "merchant_name"), ("업소", "merchant_name"),
    ("집행장소", "place"), ("사용장소", "place"), ("장소", "place"), ("사용처", "place"), ("집행처", "place"),
    ("주소", "merchant_address"), ("소재지", "merchant_address"), ("위치", "merchant_address"),
    ("집행목적", "purpose"), ("사용목적", "purpose"), ("집행내역", "purpose"), ("사용내역", "purpose"), ("목적", "purpose"),
    ("내역", "purpose"), ("내용", "purpose"),
    ("결제", "payment_method"), ("방법", "payment_method"), ("지급", "payment_method"),
]
SUB_FIELDS = {"일자": "date", "시간": "time", "상호명": "merchant_name", "상호": "merchant_name", "장소": "place",
              "주소": "merchant_address", "금액": "amount", "가맹점명": "merchant_name"}
TOTAL_RE = re.compile(r"^(합\s*계|총\s*계|소\s*계|계|누\s*계)")
ROLE_WORDS = re.compile(r"의장|위원장|위원회|의원|국장|팀장|팀|담당|사무국|전문위원|교섭단체|대표|과장|실장|비서|주무관|의회|단체|간사|사무처|의정|행정|의사")
PARTY = [("국민의힘", "국민의힘"), ("민주", "더불어민주당"), ("더불어", "더불어민주당"), ("국힘", "국민의힘")]


def map_header(cells, sub=None):
    mapping = {}
    for i, c in enumerate(cells):
        top = squash(c)
        s_ = squash(sub[i]) if sub and i < len(sub) else ""
        field = SUB_FIELDS.get(s_)
        key = s_ or top
        if field is None and key:
            if key.lower().rstrip(".") == "no":
                field = "row_no"
            else:
                field = next((f for kw, f in HEADER_KEYWORDS if kw in key), None)
        if field:
            mapping.setdefault(field, []).append(i)
    if "place" in mapping:
        if "merchant_name" in mapping:
            mapping["merchant_address"] = mapping["place"] + mapping.get("merchant_address", [])
        else:
            mapping["merchant_name"] = mapping["place"]
        del mapping["place"]
    # 집행목적이 '의정운영공통경비지출' 같은 상투 문구이고 '집행내역/집행내용'이 따로 있으면 구체적인 쪽을 먼저 쓴다
    if len(mapping.get("purpose", [])) > 1:
        label = lambda j: squash(sub[j]) if sub and j < len(sub) and squash(sub[j]) else squash(cells[j])
        mapping["purpose"].sort(key=lambda j: 0 if ("내역" in label(j) or "내용" in label(j)) else 1)
    if len(mapping.get("attendees", [])) > 1:
        label = lambda j: squash(cells[j])
        mapping["attendees"].sort(key=lambda j: 0 if "인원" in label(j) else 1)
    if "amount" in mapping and "date" in mapping and len(mapping) >= 4:
        # '사용일시' 오른쪽의 이름 없는 열이 시간인 서식
        if "time" not in mapping:
            j = mapping["date"][0] + 1
            if j < len(cells) and not squash(cells[j]) and not (sub and j < len(sub) and squash(sub[j])):
                mapping["time"] = [j]
        return mapping
    return None


def budget_from_text(*texts):
    t = squash(" ".join(x or "" for x in texts))
    if "공통경비" in t or "의정운영공통" in t:
        return "의정운영공통경비"
    if "의회운영" in t or "의장단" in t or "위원장" in t or re.search(r"(?<![가-힣])부?의장", t) or "교섭단체" in t:
        return "의회운영업무추진비"
    if "시책" in t:
        return "시책추진업무추진비"
    if "기관운영" in t or "사무국" in t:
        return "기관운영업무추진비"
    return None


def role_from_text(*texts):
    # '11월복지도시위원장'에서 '월'이 직책에 붙지 않도록 날짜 표현을 구분자로 바꾼다
    t = re.sub(r"20\d{2}\s*년|\d{1,2}\s*월|\d\s*분기|\d+", "|", " | ".join(x or "" for x in texts))
    t = squash(t)
    if "교섭단체" in t:
        for k, v in PARTY:
            if k in t:
                return "교섭단체 " + v
        return "교섭단체"
    m = re.search(r"([가-힣]{2,10}?위원장)", t)
    if m and not m.group(1).startswith(("의회운영업무추진", "업무추진")):
        return m.group(1)
    if "부의장" in t:
        return "부의장"
    if re.search(r"(?<![가-힣])의장(?!단)", t) or t.startswith("의장"):
        return "의장"
    if "사무국" in t:
        return "의회사무국"
    return None


TIME_ONLY = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
ROLE_TYPOS = {"위원징": "위원장"}


def clean_role(raw, ctx):
    """사용자 칸 정리: 개인 성명이 있으면 직책만 남긴다. 시각이 잘못 들어간 칸은 비운다(원문 오기)."""
    r = norm(raw)
    if not r or TIME_ONLY.match(r):
        return None
    r = re.sub(r"\s+", " ", r)
    for bad, good in ROLE_TYPOS.items():
        r = r.replace(bad, good)
    if "교섭" in r:  # '교섭대표-국민의힘', '교섭단체대표의원(민주)' → '교섭단체 국민의힘'
        for k in (squash(r), squash(ctx["doc_title"]), squash(ctx["post_title"])):  # 사용자 칸 우선
            for key, party in PARTY:
                if key in k:
                    return "교섭단체 " + party
        return "교섭단체"
    # '의장 홍길동', '복지도시위원장 홍길동', '홍길동 의원'
    m = re.match(r"^(.*?(의장|부의장|위원장|대표의원|전문위원|국장|팀장|담당|과장|실장|비서실장))\s*[(（]?\s*[가-힣]{2,4}\s*[)）]?$", r)
    if m and ROLE_WORDS.search(m.group(1)):
        return m.group(1).strip()
    m = re.match(r"^[가-힣]{2,4}\s*(의원|위원)$", r)
    if m:
        return m.group(1)
    if re.fullmatch(r"[가-힣]{2,4}", r) and not ROLE_WORDS.search(r):
        return role_from_text(ctx["doc_title"], ctx["post_title"]) or "미기재"
    return r


def _is_black(color):
    if isinstance(color, (list, tuple)):
        return len(color) > 0 and all(isinstance(v, (int, float)) and v == 0 for v in color)
    return color in (0, 0.0)


def fill_merged_roles(page, table, rows, carry):
    """세로 병합된 '사용자' 칸: 직책 글자는 블록 가운데 한 번만 찍힌다(종로구 2024년 초 서식).
    검은 가로선(굵은 테두리)으로 블록을 나누고, 블록 안에 찍힌 직책을 그 블록의 빈 행에 채운다.
    페이지 첫 블록에 직책이 없으면 앞 페이지 마지막 직책이 이어진 것으로 본다."""
    header = rows[0] if rows else []
    col = next((j for j, c in enumerate(header) if c and "사용자" in squash(c)), None)
    if col is None or not any(len(r) > col and not squash(r[col]) for r in rows[1:]):
        return carry
    hcell = table.rows[0].cells[col]
    if not hcell:
        return carry
    x0, top_h, x1, bottom_h = hcell
    edges = sorted({round(e["top"]) for e in page.edges if e["orientation"] == "h" and e["x0"] <= x0 + 4 and e["x1"] >= x1 - 4
                    and e["top"] > bottom_h + 1 and _is_black(e.get("non_stroking_color"))})
    bounds = []
    for y in edges:
        if not bounds or y - bounds[-1] > 2:
            bounds.append(y)
    bounds = [bottom_h] + bounds + [page.height]
    words = [w for w in page.extract_words() if x0 - 1 <= w["x0"] and w["x1"] <= x1 + 1 and w["top"] > bottom_h]
    seg_label = []
    for a, b in zip(bounds, bounds[1:]):
        ws = sorted((w for w in words if a <= (w["top"] + w["bottom"]) / 2 < b), key=lambda w: (round(w["top"]), w["x0"]))
        seg_label.append("".join(w["text"] for w in ws) or None)
    for i, r in enumerate(rows[1:], start=1):
        if len(r) <= col or squash(r[col]):
            continue
        if i >= len(table.rows):
            break
        cy = (table.rows[i].bbox[1] + table.rows[i].bbox[3]) / 2
        k = next((s for s, (a, b) in enumerate(zip(bounds, bounds[1:])) if a <= cy < b), None)
        if k is None:
            continue
        label = seg_label[k] or (carry if k == 0 else None)
        if label:
            r[col] = label
    last = next((lab for lab in reversed(seg_label) if lab), None)
    return last or carry


def rows_from_words(page, table):
    """표 추출이 헤더만 돌려주는 PDF(은평 2026년 사무국 서식): 헤더 칸의 x 범위로 단어를 열에 배정해 행을 만든다."""
    hdr = table.rows[0]
    bounds = [c for c in hdr.cells]
    if any(b is None for b in bounds):
        return None
    header = [squash(page.crop(b).extract_text() or "") for b in bounds]
    words = [w for w in page.extract_words() if w["top"] > hdr.bbox[3] + 1]
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]) <= 3:
            lines[-1][1].append(w)
        else:
            lines.append([w["top"], [w]])
    out = [header]
    for _, ws in lines:
        row = [""] * len(bounds)
        for w in ws:
            cx = (w["x0"] + w["x1"]) / 2
            k = next((j for j, b in enumerate(bounds) if b[0] - 1 <= cx <= b[2] + 1), None)
            if k is not None:
                row[k] = (row[k] + " " + w["text"]).strip()
        out.append(row)
    return out


LINE_DATE = re.compile(r"20\d{2}\s*[-.]\s*\d{1,2}\s*[-.]\s*\d{1,2}")


def rows_below(page, table, limit):
    """아래 테두리가 그려지지 않아 표 영역 밖으로 빠진 마지막 행(은평 2026년 서식)을 같은 열 위치로 읽어 온다."""
    ref = max(table.rows, key=lambda r: sum(c is not None for c in r.cells))
    bounds = ref.cells
    if any(b is None for b in bounds):
        return []
    words = [w for w in page.extract_words() if table.bbox[3] - 1 < w["top"] < limit]
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]) <= 3:
            lines[-1][1].append(w)
        else:
            lines.append([w["top"], [w]])
    out = []
    for _, ws in lines:
        if not LINE_DATE.search(" ".join(w["text"] for w in ws)):
            continue
        row = [""] * len(bounds)
        for w in ws:
            cx = (w["x0"] + w["x1"]) / 2
            k = next((j for j, b in enumerate(bounds) if b[0] - 1 <= cx <= b[2] + 1), None)
            if k is not None:
                row[k] = (row[k] + " " + w["text"]).strip()
        out.append(row)
    return out


def title_purpose(titles):
    """표에 목적 칸이 없고 제목 줄에 '사용목적 : …'이 있는 서식(용산 2022년 엑셀)."""
    for t in titles:
        m = re.search(r"사용\s*목적\s*[:：]\s*(.+)", t)
        if m:
            return norm(m.group(1))
    return None


def raw_rows_pdf(path):
    rows = []
    carry = None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = page.find_tables()
            for ti, table in enumerate(tables):
                trows = [list(r) for r in table.extract()]
                rebuilt = None
                if len(trows) <= 2 and trows and map_header(["" if c is None else str(c) for c in trows[0]]):
                    rebuilt = rows_from_words(page, table)
                    if rebuilt and len(rebuilt) > len(trows):
                        trows = rebuilt
                    else:
                        rebuilt = None
                if rebuilt is None:  # 단어 위치로 다시 만든 표는 이미 아래쪽 줄까지 모두 읽었다
                    limit = tables[ti + 1].bbox[1] if ti + 1 < len(tables) else page.height - 15
                    trows += rows_below(page, table, limit)
                carry = fill_merged_roles(page, table, trows, carry)
                rows.extend(trows)
    return rows


def pdf_text_kind(path):
    """'text' / 'scanned'(이미지) / 'outlined'(글자가 도형으로 변환되어 텍스트 없음)"""
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages[:3]
        chars = sum(len(p.chars) for p in pages)
        if chars >= 30 * len(pages):  # 쪽 번호 몇 글자만 있는 경우는 텍스트 없음으로 본다
            return "text"
        return "scanned" if any(p.images for p in pages) else "outlined"


def rows_to_records(rows, ctx):
    recs, skipped, totals = [], [], []
    mapping = None
    last_role = None
    header_width = 0
    titles = []  # 시트 이름과 표 위의 제목 행들('업무추진비 사용내역(의장, 2022년 11월)')
    last_budget_raw = None
    i = 0
    while i < len(rows):
        r = rows[i]
        i += 1
        if r and r[0] == "__SHEET__":
            mapping, last_role, last_budget_raw, titles = None, None, None, [str(r[1])]
            continue
        cells = list(r)
        str_cells = ["" if c is None else str(c) for c in cells]
        if not any(s.strip() for s in str_cells):
            continue
        filled = [s for s in str_cells if s.strip()]
        if mapping is None and filled and not re.match(r"^[\d,.\s-]+$", filled[0]):
            titles.append(" ".join(filled))
        nxt = rows[i] if i < len(rows) else None
        nxt_strs = [("" if v is None else str(v)) for v in nxt] if nxt else []
        # 보조 헤더(일자/시간/상호명…)는 '다음 표의 헤더 행'이나 날짜가 든 데이터 행과 구분해야 한다
        has_sub = (bool(nxt) and nxt[0] != "__SHEET__" and any(squash(v) in SUB_FIELDS for v in nxt if v is not None)
                   and not map_header(nxt_strs) and not any(re.search(r"20\d{2}\s*[-.]\s*\d", s_) for s_ in str_cells))
        hdr = map_header(str_cells, [("" if v is None else str(v)) for v in nxt] if has_sub else None)
        if hdr:
            mapping = hdr
            header_width = len(str_cells)
            last_budget_raw = None
            if has_sub:
                i += 1
            continue
        if mapping is None:
            continue
        # 다음 쪽 표에 앞쪽 열(예: 은평 '구분')이 빠져 열이 왼쪽으로 밀린 경우: 날짜가 있어야 할 칸을 기준으로 다시 맞춘다
        dcol = mapping["date"][0]
        if len(cells) < header_width and not (dcol < len(cells) and parse_date(cells[dcol], ctx["period"]) not in (None, "INVALID")):
            k = next((j for j, c in enumerate(cells) if c not in (None, "") and re.match(r"^\s*20\d{2}\s*[-.]", str(c))), None)
            if k is not None and k < dcol:
                cells = [None] * (dcol - k) + cells
                str_cells = ["" if c is None else str(c) for c in cells]

        def g(f):
            for j in mapping.get(f, []):
                if j < len(cells) and cells[j] not in (None, ""):
                    return cells[j]
            return None

        first = squash(next((s for s in str_cells if s.strip()), ""))
        amt = parse_amount(g("amount"))
        if TOTAL_RE.match(first) or "합계" in first or first.startswith("총사용") or first.startswith("총액"):
            if amt is not None:
                totals.append(amt)
            continue
        dval = g("date")
        if isinstance(dval, str):
            dval = dval.strip().rstrip(".").strip()  # '10.1.' 같은 짧은 날짜
        d = parse_date(dval, ctx["period"])
        if d == "INVALID" or (d is None and amt is not None and dval not in (None, "")):
            skipped.append({"reason": "날짜 형식 오류", "cells": [norm(s) for s in str_cells][:12]})
            continue
        if d is None or amt is None:
            if recs and d is None and amt is None and parse_amount(g("row_no")) is None:
                for f in ("merchant_name", "purpose"):  # 줄바꿈으로 다음 행에 이어진 글자
                    extra = norm(g(f))
                    if extra and recs[-1].get(f):
                        recs[-1][f] = norm(recs[-1][f] + " " + extra)
                        recs[-1]["parse_confidence"] = "MEDIUM"
            elif d is not None and amt is None and g("amount") not in (None, ""):
                skipped.append({"reason": "금액 판독 불가", "cells": [norm(s) for s in str_cells][:12]})
            continue
        t = parse_time(g("time"))
        if t is None and isinstance(dval, str) and len(dval) > 10:
            t = parse_time(dval[10:])
        role_cell = norm(g("user_role"))
        if t is None and role_cell and TIME_ONLY.match(role_cell):
            t = parse_time(role_cell)  # 원문 오기: 사용자 칸에 승인시각
        merchant, addr = split_merchant(g("merchant_name"), g("merchant_address"))
        budget_raw = norm(g("budget_item"))
        if budget_raw is None and "budget_item" in mapping:
            budget_raw = last_budget_raw  # 세로 병합된 '구분' 칸
        last_budget_raw = budget_raw or last_budget_raw
        role_in_budget = None
        if budget_raw:  # '의회운영업무추진비 (의장)' → 비목 + 직책
            bm = re.search(r"[(（]([^)）]+)[)）]", budget_raw)
            if bm and ROLE_WORDS.search(bm.group(1)):
                role_in_budget = re.sub(r"\s+", "", bm.group(1))
        if budget_raw and canon_budget(budget_raw) in ("의정운영공통경비", "의회운영업무추진비", "기관운영업무추진비", "시책추진업무추진비"):
            budget, inferred = canon_budget(budget_raw), False
        elif budget_raw and "부서" in budget_raw:
            budget, inferred = "부서운영업무추진비", False
        else:
            budget, inferred = ctx["budget"] or budget_from_text(*titles), True
        if "user_role" in mapping:
            role = clean_role(g("user_role"), ctx)
            if role is None:
                role = last_role  # 세로 병합 셀
            last_role = role or last_role
        else:
            role = None
        if not role and role_in_budget:
            role = clean_role(role_in_budget, ctx)
        if not role:
            role = next((x for x in (role_from_text(t) for t in titles) if x), None) \
                or role_from_text(ctx["doc_title"], ctx["post_title"]) or norm(g("department"))
        if not role:
            # 사용자 칸이 없는 공통경비 파일은 의회 명의, 사무국 파일은 사무국 명의
            role = ctx["council"] if budget == "의정운영공통경비" else "의회사무국" if budget in (
                "기관운영업무추진비", "시책추진업무추진비", "부서운영업무추진비") else None
        if budget is None and role and re.search(r"의장|위원장|교섭단체", role):
            budget = "의회운영업무추진비"  # 직책 사용분 = 의회운영업무추진비 (추정, budget_item_inferred)
        low_conf = False
        if not role:
            role, low_conf = ctx["council"], True  # 문서에서 사용자를 정할 수 없음 — 의회 명의로 두고 신뢰도 낮춤
        wrapped = any("\n" in s for s in str_cells)
        recs.append({
            "source_id": ctx["slug"],
            "council": ctx["council"],
            "doc_id": ctx["doc_id"],
            "doc_title": ctx["doc_title"],
            "doc_url": ctx["doc_url"],
            "post_url": ctx["post_url"],
            "period": ctx["period"],
            "row_no": parse_amount(g("row_no")),
            "budget_item": budget,
            "budget_item_inferred": inferred,
            "department": norm(g("department")),
            "user_role": role,
            "date": d,
            "time": t,
            "amount": amt,
            "merchant_name": merchant,
            "merchant_address": addr,
            "purpose": norm(g("purpose")) or title_purpose(titles),
            "attendees": next((n for n in (parse_attendees(cells[j]) for j in mapping.get("attendees", []) if j < len(cells)) if n), None),
            "payment_method": canon_payment(norm(g("payment_method"))),
            "parse_confidence": "LOW" if low_conf else "MEDIUM" if (wrapped and not merchant) else "HIGH",
        })
    return recs, skipped, totals


def parse(slug, cfg):
    raw_dir = ROOT / "data" / "raw" / slug
    mpath = raw_dir / "manifest.json"
    if not mpath.exists():
        print(f"[{slug}] no manifest", file=sys.stderr)
        return
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    files, records, seen = [], [], {}
    council_keys = set()  # 이미 파싱한 문서들의 거래 키 (작업용 복사 시트 판별용)
    for post in sorted(manifest, key=lambda p: (p.get("period") or "", p.get("posted_date") or "")):
        for att in post["attachments"]:
            entry = {"file": att["filename"], "period": post.get("period"), "post_title": post["post_title"]}
            if att.get("error"):
                files.append({**entry, "status": "unparsed", "rows": 0, "amount_sum": 0, "reason": f"다운로드 실패: {att['error']}"})
                continue
            entry["doc_id"] = f"{slug}:" + att["sha256"][:12]
            if "명단" in att["filename"]:
                files.append({**entry, "status": "skipped", "rows": 0, "amount_sum": 0, "reason": "참석자 명단(개인 성명 포함) — 파싱 대상 아님"})
                continue
            if att["sha256"] in seen:
                files.append({**entry, "status": "skipped", "rows": 0, "amount_sum": 0,
                              "reason": f"동일 파일이 이전 게시글({seen[att['sha256']]})에 이미 첨부됨"})
                continue
            seen[att["sha256"]] = post["post_title"]
            path = ROOT / att["local_path"]
            ext = path.suffix.lower()
            ctx = {"slug": slug, "council": cfg["name"], "doc_id": entry["doc_id"], "doc_title": att["filename"],
                   "doc_url": att["url"], "post_url": post["post_url"], "period": post.get("period"),
                   "post_title": post["post_title"],
                   "budget": budget_from_text(att["filename"]) or budget_from_text(post["post_title"])}
            try:
                rows = []
                if ext == ".pdf":
                    kind = pdf_text_kind(path)
                    if kind != "text" or pdf_is_image_text(path):
                        reason = "스캔 이미지 PDF — 글자 데이터 없음(OCR 필요)" if kind != "outlined" else "글자가 도형(외곽선)으로 변환된 PDF — 글자 데이터 없음(OCR 필요)"
                        files.append({**entry, "status": "unparsed", "rows": 0, "amount_sum": 0, "reason": reason})
                        continue
                    rows = raw_rows_pdf(path)
                elif ext in (".xlsx", ".xls", ".xlsm"):
                    rows = None
                    recs, skipped, totals, dropped = [], [], [], []
                    seen_keys = set()
                    ps, pe = period_range(ctx["period"]) if ctx["period"] else (None, None)
                    for name, srows in sheets_xlsx(path):
                        r_, s_, t_ = rows_to_records([["__SHEET__", name]] + srows, ctx)
                        if not r_:
                            continue
                        keys = [(x["date"], x["time"], x["amount"], x["merchant_name"]) for x in r_]
                        dup = sum(k in seen_keys or k in council_keys for k in keys) / len(keys)
                        if recs and dup >= 0.8:
                            dropped.append(f"{name}({len(r_)}행, 앞 시트·이전 문서와 {dup:.0%} 중복)")
                            continue  # 앞 시트나 이전 문서를 베낀 작업용 시트
                        seen_keys.update(keys)
                        recs += r_
                        skipped += s_
                        totals += t_
                else:
                    files.append({**entry, "status": "unparsed", "rows": 0, "amount_sum": 0, "reason": f"지원하지 않는 형식({ext}) — 수동 확인 필요"})
                    continue
                if rows is not None:
                    recs, skipped, totals = rows_to_records(rows, ctx)
                    dropped = []
            except Exception as e:  # noqa: BLE001 - 손상 파일 등은 보고서에 남긴다
                files.append({**entry, "status": "unparsed", "rows": 0, "amount_sum": 0, "reason": f"파싱 오류: {e}"[:200]})
                continue
            if not recs:
                empty = ext == ".pdf" and pdf_says_empty(path)
                files.append({**entry, "status": "parsed" if empty else "unparsed", "rows": 0, "amount_sum": 0,
                              "reason": "집행 실적 없음(빈 서식)" if empty else "집행내역 표를 찾지 못함"})
                continue
            out_of_period = 0
            if ctx["period"]:
                s, e = period_range(ctx["period"])
                out_of_period = sum(1 for r in recs if not (s <= r["date"] <= e))
            council_keys.update((x["date"], x["time"], x["amount"], x["merchant_name"]) for x in recs)
            files.append({**entry, "status": "parsed", "rows": len(recs), "amount_sum": sum(r["amount"] for r in recs),
                          "printed_totals": totals[:5], "rejected_rows": skipped[:20], "rows_outside_period": out_of_period,
                          "dropped_sheets": dropped, "reason": None})
            records.extend(recs)
    out = STAGING / f"{slug}.jsonl"
    with open(out, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (STAGING / f"{slug}_parse_report.json").write_text(json.dumps({"files": files}, ensure_ascii=False, indent=1), encoding="utf-8")
    # 수집 범위는 행 날짜(오기 포함)가 아니라 파싱된 문서의 공개 대상 기간으로 계산
    periods = sorted(m for f in files if f["status"] == "parsed" and f.get("rows") and f.get("period")
                     for m in (period_range(f["period"])[0][:7], period_range(f["period"])[1][:7]))
    reg = {
        "source_id": slug, "name": cfg["name"], "region": cfg["region"], "board_url": cfg["board"], "term_base_2018": 8,
        "formats": sorted({Path(a["local_path"]).suffix.lower().lstrip(".") for p in manifest for a in p["attachments"] if a.get("local_path")}),
        "collected_from": periods[0] if periods else None, "collected_to": periods[-1] if periods else None,
        "notes": cfg.get("notes", ""),
    }
    (STAGING / "councils").mkdir(parents=True, exist_ok=True)
    (STAGING / "councils" / f"{slug}.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    st = {}
    for f in files:
        st[f["status"]] = st.get(f["status"], 0) + 1
    print(f"[{slug}] {len(records)} rows; files {st}", file=sys.stderr)
