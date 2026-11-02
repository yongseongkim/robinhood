"""서울특별시의회 업무추진비 첨부(PDF·XLSX) → data/staging/seoul.jsonl

- 표의 헤더 이름으로 열을 매핑한다 (서식이 위원회·부서마다 다르다).
- '사용자' 열이 없으면 게시글 제목에서 직책·위원회를 정한다. 작성자(성명일 수 있음)는 쓰지 않고
  post_author 로만 남긴다.
- 의회운영업무추진비는 직책(의장·부의장·상임위원장·교섭단체 대표)의 경비이므로 위원회 게시글이면
  '<위원회명>위원장', 의정운영공통경비는 '<위원회명>위원회'로 둔다.
"""
import json
import re
import sys
import warnings
from datetime import date, datetime, time
from pathlib import Path

import openpyxl

from common import period_range
import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "seoul"
OUT = ROOT / "data" / "staging" / "seoul.jsonl"
REPORT = ROOT / "data" / "staging" / "seoul_parse_report.json"
warnings.filterwarnings("ignore")

# (키워드, 필드) — 앞에 있는 규칙이 우선. '사용자 및 인원'은 인원 정보라 '인원'을 '사용자'보다 먼저 본다.
HEADER_KEYWORDS = [
    ("연번", "row_no"), ("번호", "row_no"), ("순번", "row_no"),
    ("인원", "attendees"), ("집행대상", "attendees"),
    ("사용자", "user_role"),
    ("위원회명", "department"), ("부서", "department"),
    ("비목", "budget_item"), ("과목", "budget_item"),
    ("시간", "time"),
    ("집행일시", "date"), ("사용일시", "date"), ("일시", "date"), ("집행일", "date"), ("사용일", "date"), ("일자", "date"),
    ("금액", "amount"),
    ("가맹점", "merchant_name"), ("상호", "merchant_name"),
    ("집행장소", "place"), ("사용장소", "place"), ("장소", "place"), ("사용처", "place"),
    ("주소", "merchant_address"), ("소재지", "merchant_address"),
    ("집행목적", "purpose"), ("사용목적", "purpose"), ("집행내역", "purpose"), ("사용내역", "purpose"), ("목적", "purpose"),
    ("내역", "purpose"), ("내용", "purpose"),
    ("결제", "payment_method"), ("방법", "payment_method"),
]
SUB_LABELS = {"일자", "시간", "상호명", "상호", "주소", "장소", "금액"}
DATE_RE = re.compile(r"(20\d{2})\s*[-./년]+\s*(\d{1,2})\s*[-./월]+\s*(\d{1,2})")
SHORT_DATE_RE = re.compile(r"^(\d{1,2})\s*[-./월]+\s*(\d{1,2})\s*일?$")
TIME_RE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})")
TOTAL_RE = re.compile(r"^(합\s*계|총\s*계|소\s*계|계|누\s*계)")
ADDR_HINT = re.compile(r"(구|시|군|동|로|길|읍|면)\s*\d|[가-힣]+(구|시|군)\s*[가-힣]")


def norm(s):
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s).replace("　", " ")).strip()
    return s or None


def squash(s):
    return re.sub(r"\s+", "", str(s or ""))


def map_header(cells, sub=None):
    """{필드: [열 번호...]} — 병합 셀로 같은 이름의 열이 여럿이면 모두 보관하고 값이 있는 첫 열을 쓴다."""
    mapping = {}
    carry = ""
    for i, c in enumerate(cells):
        top = squash(c)
        if top:
            carry = top
        s_ = squash(sub[i]) if sub and i < len(sub) else ""
        key = s_ if s_ else top
        if not key:
            continue
        field = {"일자": "date", "시간": "time", "상호명": "merchant_name", "상호": "merchant_name", "장소": "place",
                 "주소": "merchant_address", "금액": "amount"}.get(s_)
        if field is None:
            k = key.lower().rstrip(".")
            if k == "no":
                field = "row_no"
            else:
                field = next((f for kw, f in HEADER_KEYWORDS if kw in key), None)
        if field:
            mapping.setdefault(field, []).append(i)
    # '가맹점명'과 '집행장소'가 함께 있으면 집행장소는 주소, 아니면 집행장소가 상호
    if "place" in mapping:
        if "merchant_name" in mapping:
            mapping.setdefault("merchant_address", [])
            mapping["merchant_address"] = mapping["place"] + mapping["merchant_address"]
        else:
            mapping["merchant_name"] = mapping["place"]
        del mapping["place"]
    if "amount" in mapping and "date" in mapping and len(mapping) >= 4:
        return mapping
    return None


LABEL_VOCAB = sorted(["결제방법", "결제수단", "부서명", "위원회명", "상호명", "가맹점명", "집행일자", "집행일시", "집행시간", "집행장소",
                      "집행목적", "집행금액", "집행내역", "대상인원", "사용일", "사용시간", "사용장소", "사용목적", "사용금액", "연번", "일자",
                      "시간", "주소", "목적", "금액", "인원", "장소", "비목", "사용자", "번호", "내역", "비고"], key=len, reverse=True)


def split_merged_header(cells):
    """'연번 부 서 명 일 자 시 간' 처럼 한 셀에 여러 헤더가 합쳐진 행을 알려진 이름 단위로 나눈다."""
    text = squash("".join(c or "" for c in cells))
    tokens, i = [], 0
    while i < len(text):
        lab = next((l for l in LABEL_VOCAB if text.startswith(l, i)), None)
        if not lab:
            return None
        tokens.append(lab)
        i += len(lab)
    return tokens if len(tokens) == len(cells) else None


def parse_amount(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    t = re.sub(r"[,원\s]", "", str(v)).replace("△", "-").replace("▲", "-")
    if re.fullmatch(r"\(\d+\)", t):
        t = "-" + t[1:-1]
    return int(float(t)) if re.fullmatch(r"-?\d+(\.\d+)?", t) else None


def parse_date(v, period):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 30000 < v < 60000:
        return date.fromordinal(date(1899, 12, 30).toordinal() + int(v)).isoformat()
    t = str(v).strip()
    try:
        m = re.fullmatch(r"(20\d{2})(\d{2})(\d{2})(?:\.0)?", t)  # '20260204', 20260123
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        m = DATE_RE.search(t)
        if m:
            y, mo, d = map(int, m.groups())
            return date(y, mo, d).isoformat()
        m = re.fullmatch(r"(20\d{2})\s*[-./:]\s*(\d{1,2})\s*[-./:]?\s*(\d{2})", t)  # 원문 오기 '2023-12:06', '2024-0105'
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        m = re.match(r"^(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", t)  # '26.09.02'
        if m:
            return date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        m = SHORT_DATE_RE.match(t) or re.match(r"^(\d{1,2})\s*월\s*(\d{1,2})\s*일", t)
        if m and period:
            mo, d = int(m.group(1)), int(m.group(2))
            y = int(period[:4]) - (1 if period[5:7] == "01" and mo == 12 else 0)
            return date(y, mo, d).isoformat()
    except ValueError:
        return "INVALID"
    return None


def parse_time(v):
    if v is None:
        return None
    if isinstance(v, (time, datetime)):
        return f"{v.hour:02d}:{v.minute:02d}"
    if isinstance(v, float) and 0 <= v < 1:
        mins = round(v * 1440)
        return f"{mins // 60:02d}:{mins % 60:02d}"
    m = TIME_RE.search(str(v))
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        h = int(m.group(1))
        h += 12 if "오후" in str(v) and h < 12 else 0
        h = 0 if "오전" in str(v) and h == 12 else h
        return f"{h:02d}:{m.group(2)}"
    m = re.fullmatch(r"\s*(\d{2})(\d{2})\s*", str(v))
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return f"{m.group(1)}:{m.group(2)}"
    return None


def parse_attendees(v):
    """'부의장외10명' → 11, '직원38명' → 38, '위원장 등 5명' → 5, 12 → 12. 원문은 보관하지 않는다."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) or None
    s = squash(v)
    m = re.search(r"외(\d+)(명|인)?", s)
    if m:
        return int(m.group(1)) + 1
    m = re.search(r"등(\d+)(명|인)?$", s)
    if m:
        return int(m.group(1))
    nums = [int(x) for x in re.findall(r"(\d+)(?:명|인)", s)]
    if nums:
        return sum(nums) if len(nums) > 1 and "," in str(v) else max(nums)
    m = re.fullmatch(r"(\d+)", s)
    return int(m.group(1)) if m else None


def split_merchant(name, addr):
    """'전설의우대갈비\\n(마포구월드컵북로396)' → ('전설의우대갈비', '마포구월드컵북로396')"""
    if name is None:
        return None, norm(addr)
    raw = str(name)
    if addr is None:
        m = re.match(r"^(.*?)\s*[\n ]?\(([^()]*)\)\s*$", raw, flags=re.S)
        if m and ADDR_HINT.search(m.group(2)):
            return norm(m.group(1)), norm(m.group(2))
        parts = raw.split("\n")
        if len(parts) >= 2 and ADDR_HINT.search(parts[-1]):
            return norm(" ".join(parts[:-1])), norm(parts[-1].strip("()"))
    return norm(raw), norm(addr)


ROLE_ALIASES = {"예결위": "예산결산특별위원회", "예산결산위원회": "예산결산특별위원회", "예결위원장": "예산결산특별위원장",
                "예산결산위원장": "예산결산특별위원장", "예산결산전문위원실": "예산결산특별위원회",
                "예산결산특별전문위원실": "예산결산특별위원회"}

PARTY_RE = re.compile(r"(국민의힘|더불어민주당|정의당|진보당|조국혁신당|개혁신당|국민의당|기본소득당)")

COMMITTEES = ["운영", "행정자치", "기획경제", "환경수자원", "문화체육관광", "보건복지", "도시안전건설", "주택공간", "주택균형개발",
              "도시계획균형", "도시계획관리", "교통", "교육", "예산결산특별", "윤리특별", "정책", "도시계획", "주택"]


def role_from_title(title, filename, budget):
    t = squash(title) + " " + squash(filename)
    m = re.search(r"(교섭지원\d팀)", t)
    if m:
        return m.group(1)
    if re.search(r"(제?1부의장|제1부의장)", t):
        return "제1부의장"
    if re.search(r"(제?2부의장)", t):
        return "제2부의장"
    if "예결위" in t:
        t = t.replace("예결위", "예산결산특별위원회")
    for c in sorted(COMMITTEES, key=len, reverse=True):
        if c + "위원회" in t or c + "위원장" in t or c + "전문위원실" in t:
            name = c + "위원회"
            if budget == "의회운영업무추진비":
                return name[:-1] + "장"  # 보건복지위원회 → 보건복지위원장
            return name
    if re.search(r"(?<!부)의장", squash(title)):
        return "의장"
    m = re.search(r"(?:\d+월|\d분기)\s+(.+?)\s+(?:의정운영공통경비|의회운영업무추진비|업무추진비)", title)
    if m:
        name = re.sub(r"^운영지원과\s+", "", m.group(1)).replace("서울특별시의회", "서울특별시의회").strip()
        return re.sub(r"\s+", "", name)
    return None


def budget_from_text(*texts):
    # '의정운영업무추진비카드사용내역' 같은 파일명은 의회운영업무추진비 — '업무추진비'를 '의정운영'보다 먼저 본다
    t = squash(" ".join(x or "" for x in texts))
    if "공통경비" in t:
        return "의정운영공통경비"
    if "업무추진비" in t or "의회운영" in t:
        return "의회운영업무추진비"
    if "의정운영" in t:
        return "의정운영공통경비"
    return None


def canon_payment(s):
    """'5카명드'·'카드 방객'처럼 옆 칸 글자가 섞인 결제방법을 정리한다."""
    k = squash(s)
    if not k:
        return None
    for word, canon in (("제로페이", "제로페이"), ("계좌", "계좌이체"), ("이체", "계좌이체"), ("현금", "현금"), ("고지서", "고지서"), ("카", "카드")):
        if word in k:
            return canon
    return norm(s)


def canon_budget(s):
    k = squash(s)
    if not k:
        return None
    if k in ("기관", "기관운영"):
        return "기관운영업무추진비"
    if k in ("시책", "시책추진"):
        return "시책추진업무추진비"
    if "공통" in k or "의정운영" in k:
        return "의정운영공통경비"
    if "의회운영" in k:
        return "의회운영업무추진비"
    if "기관운영" in k:
        return "기관운영업무추진비"
    if "시책" in k:
        return "시책추진업무추진비"
    return norm(s)


def pdf_is_image_text(path):
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        return len(page.images) > 5 and not re.search(r"[가-힣]{2}", text)


def text_fallback(path, ctx):
    with pdfplumber.open(path) as pdf:
        lines = [l for p in pdf.pages for l in (p.extract_text() or "").split("\n")]
    out = []
    for m in records_from_text_lines(lines):
        merchant, addr = split_merchant(m["place"], None)
        budget = ctx["budget"]
        out.append({
            "source_id": "seoul", "council": "서울특별시의회", "doc_id": ctx["doc_id"], "doc_title": ctx["doc_title"],
            "doc_url": ctx["doc_url"], "post_url": ctx["post_url"], "period": ctx["period"], "row_no": int(m["no"]),
            "budget_item": budget, "budget_item_inferred": True, "department": norm(m["dept"]),
            "user_role": role_from_title(ctx["post_title"], ctx["doc_title"], budget),
            "date": m["date"], "time": parse_time(m["time"]), "amount": parse_amount(m["amount"]),
            "merchant_name": merchant, "merchant_address": addr, "purpose": norm(m["purpose"]),
            "attendees": parse_attendees(m["who"]), "payment_method": canon_payment(m["pay"]),
            "parse_confidence": "MEDIUM", "post_author": ctx["post_author"],
        })
    return out


def pdf_says_empty(path):
    with pdfplumber.open(path) as pdf:
        text = squash(" ".join(p.extract_text() or "" for p in pdf.pages[:2]))
    return "내역없음" in text or "사용실적없음" in text or "집행실적없음" in text or re.search(r"사용금액합계0(?!\d|,)", text) is not None


def raw_rows_pdf(path):
    rows = []
    with pdfplumber.open(path) as pdf:
        text_chars = 0
        for page in pdf.pages:
            text = page.extract_text() or ""
            text_chars += len(text)
            tables = page.extract_tables()
            if tables:
                rows.append(["__PAGE__", text.split("\n")])
            for table in tables:
                rows.extend(list(r) for r in table)
    return rows, text_chars


TEXT_ROW_RE = re.compile(r"^(\d+)\s+(20\d{2}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}\s*일?(?:\s*\([월화수목금토일]\))?)\s*(\d{1,2}:\d{2}(?::\d{2})?)?\s*(.*)$")


LINE_DATE_RE = re.compile(r"(20\d{2}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}\s*일?|(?<![\d/])\d{2}/\d{1,2}/\d{1,2}(?![\d/]))")
LINE_TIME_RE = re.compile(r"(오전|오후)?\s*(\d{1,2}):(\d{2})(?::\d{2})?")
PAYMENTS = ("카드", "현금", "계좌이체", "제로페이", "이체", "법인카드", "신용카드")


def repair_by_content(place, amt, lines, period):
    """연번·일자 셀까지 빠진 표(정보소통광장 서식): 상호와 금액이 같은 텍스트 줄을 찾아 일자·시간·인원·결제를 읽는다."""
    key = squash(place)[:4] if place else None
    amt_pat = re.compile(r"\s*".join(re.escape(ch) for ch in f"{amt:,}"))
    for line in lines or []:
        line = line.strip()
        if not re.match(r"^\d+\s", line) or (key and key not in squash(line)):
            continue
        am = amt_pat.search(line)
        dm = LINE_DATE_RE.search(line)
        if not am or not dm:
            continue
        tm = LINE_TIME_RE.search(line, dm.end())
        t = None
        if tm and tm.start() - dm.end() < 6:
            h, mi = int(tm.group(2)), int(tm.group(3))
            h += 12 if tm.group(1) == "오후" and h < 12 else 0
            h = 0 if tm.group(1) == "오전" and h == 12 else h
            t = f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None
        tail = line[am.end():].split()
        pay = tail.pop() if tail and tail[-1] in PAYMENTS else None
        return {"date": dm.group(1), "time": t, "attendees": parse_attendees(" ".join(tail)) if tail else None,
                "payment": pay, "row_no": int(line.split()[0])}
    return None


TEXT_LINE_RE = re.compile(
    r"^(?P<no>\d+)\s+(?:(?P<dept>[^\d\s][^\s]*)\s+)?(?P<date>20\d{2}-\d{2}-\d{2})\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s+"
    r"(?P<place>.+?\))\s+(?P<purpose>.+?)\s+(?P<amount>\d{1,3}(?:,\d{3})+)\s+(?P<who>.*?)\s*(?P<pay>카드|계좌이체|현금|제로페이)?$")


def records_from_text_lines(lines):
    """표가 헤더만 추출되는 PDF(정보소통광장 서식 일부): 텍스트 줄을 직접 읽는다."""
    out = []
    for line in lines:
        m = TEXT_LINE_RE.match(line.strip())
        if m:
            out.append(m.groupdict())
    return out


def repair_from_text(row_no, purpose, lines):
    """표 추출에서 일자·장소 셀이 빠진 행을 페이지 텍스트에서 다시 읽는다."""
    for line in lines or []:
        m = TEXT_ROW_RE.match(line.strip())
        if not m or int(m.group(1)) != row_no:
            continue
        rest = m.group(4)
        place = None
        if purpose:
            k = rest.find(purpose[:8])
            place = rest[:k].strip() if k > 0 else None
        return {"date": m.group(2), "time": m.group(3), "place": place}
    return None


def sheets_xlsx(path):
    if path.suffix.lower() == ".xls":
        import xlrd  # 구형 엑셀(.xls)
        book = xlrd.open_workbook(path)
        out = []
        for sh in book.sheets():
            rows = []
            for i in range(sh.nrows):
                row = []
                for c in sh.row(i):
                    if c.ctype == xlrd.XL_CELL_DATE:
                        row.append(xlrd.xldate.xldate_as_datetime(c.value, book.datemode))
                    elif c.ctype == xlrd.XL_CELL_EMPTY:
                        row.append(None)
                    else:
                        row.append(c.value)
                rows.append(row)
            out.append((sh.name, rows))
        return out
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]


def is_blank_template(path):
    """헤더만 있고 금액이 모두 비었거나 '사용금액 합계 0'인 서식."""
    for _, rows in sheets_xlsx(path):
        for r in rows:
            cells = [c for c in r if c is not None]
            if any(isinstance(c, str) and "합계" in c for c in cells):
                nums = [c for c in cells if isinstance(c, (int, float))]
                if nums and all(n == 0 for n in nums):
                    return True
    return False


def in_period(rec, period):
    if not period:
        return True
    s, e = period_range(period)
    return s <= rec["date"] <= e


def rows_to_records(rows, ctx):
    recs, skipped, totals = [], [], []
    mapping = None
    page_lines = []
    i = 0
    while i < len(rows):
        r = rows[i]
        i += 1
        if r and r[0] == "__SHEET__":
            mapping = None
            continue
        if r and r[0] == "__PAGE__":
            page_lines = r[1]
            continue
        cells = [c for c in r]
        str_cells = ["" if c is None else str(c) for c in cells]
        if not any(s.strip() for s in str_cells):
            continue
        nxt = rows[i] if i < len(rows) else None
        has_sub = nxt is not None and nxt and nxt[0] not in ("__SHEET__", "__PAGE__") and any(squash(v) in SUB_LABELS for v in nxt if v is not None)
        hdr = map_header(str_cells, [("" if v is None else str(v)) for v in nxt] if has_sub else None)
        if not hdr and "연번" in squash("".join(str_cells)):
            tokens = split_merged_header(str_cells)
            hdr = map_header(tokens) if tokens else None
        if hdr:
            mapping = hdr
            if has_sub:
                i += 1
            continue
        if mapping is None:
            continue
        def g(f):
            for j in mapping.get(f, []):
                if j < len(cells) and cells[j] not in (None, ""):
                    return cells[j]
            return None

        first = squash(next((s for s in str_cells if s.strip()), ""))
        amt = parse_amount(g("amount"))
        if TOTAL_RE.match(first) or "합계" in first:
            if amt is not None:
                totals.append(amt)
            continue
        dval = g("date")
        repaired = None
        content_fix = None
        if dval is None and amt is not None and parse_amount(g("row_no")) is not None and page_lines:
            repaired = repair_from_text(parse_amount(g("row_no")), norm(g("purpose")), page_lines)
            if repaired:
                dval = repaired["date"]
        elif dval is None and amt is not None and g("merchant_name") and page_lines:
            content_fix = repair_by_content(norm(g("merchant_name")), amt, page_lines, ctx["period"])
            if content_fix:
                dval = content_fix["date"]
        d = parse_date(dval, ctx["period"])
        if d == "INVALID" or (d is None and amt is not None and dval not in (None, "")):
            skipped.append({"reason": "날짜 형식 오류", "cells": [norm(s) for s in str_cells][:12]})
            continue
        if d is None and amt is not None and parse_amount(g("row_no")) is None:
            totals.append(amt)  # '2026.9월 … 2,711,600' 같은 월 합계 행
            continue
        spill = None
        if d is not None and amt is None and parse_amount(g("row_no")) is not None and g("amount") not in (None, ""):
            # 집행목적 글자가 금액 칸에 넘친 경우: 칸 끝이 온전한 금액이면 금액만 취하고 앞부분은 목적에 붙인다
            m = re.match(r"^(.*?)\s*(\d{1,3}(?:,\d{3})+)\s*$", str(g("amount")), flags=re.S)
            if m and not re.search(r"\d", m.group(1)[-2:] if m.group(1) else ""):
                amt, spill = parse_amount(m.group(2)), norm(m.group(1))
            else:
                skipped.append({"reason": "금액 판독 불가(글자 겹침)", "cells": [norm(s_) for s_ in str_cells][:12]})
                continue
        if d is None or amt is None:
            # 줄바꿈으로 다음 행에 이어진 상호·목적
            if recs and d is None and amt is None and parse_amount(g("row_no")) is None:
                for f in ("merchant_name", "purpose"):
                    extra = norm(g(f))
                    if extra and recs[-1].get(f) is not None:
                        recs[-1][f] = norm(recs[-1][f] + " " + extra)
                        recs[-1]["parse_confidence"] = "MEDIUM"
            continue
        t = parse_time(g("time"))
        if t is None and "time" not in mapping and isinstance(dval, (str, datetime)):
            t = parse_time(str(dval)[10:] if isinstance(dval, str) else dval) if (isinstance(dval, datetime) and (dval.hour or dval.minute)) or (isinstance(dval, str) and len(dval) > 10) else None
        if content_fix:
            t = t or content_fix["time"]
        if repaired:
            t = t or parse_time(repaired["time"])
            merchant, addr = split_merchant(repaired["place"], None) if repaired["place"] else (None, None)
        else:
            merchant, addr = split_merchant(g("merchant_name"), g("merchant_address"))
        budget_raw = norm(g("budget_item"))
        budget, inferred = (canon_budget(budget_raw), False) if budget_raw else (ctx["budget"], True)
        role = norm(g("user_role"))
        dept = norm(g("department"))
        if role:
            role = re.sub(r"\s+", "", role)
        else:
            role = role_from_title(ctx["post_title"], ctx["doc_title"], budget)
            if not role and dept:
                role = re.sub(r"^(서울특별시의회|서울시의회|시의회사무처|의회사무처)\s*", "", dept).replace(" ", "") or "서울특별시의회"
        role = ROLE_ALIASES.get(role, role)
        # 교섭단체 경비(교섭지원N팀·대표실·정책지원담당관): 부서명·집행목적에 적힌 정당으로 교섭단체를 특정
        if ((role or "").startswith("교섭") or role == "정책지원담당관" or "대표실" in squash(dept)
                or "교섭단체" in squash(dept) or "교섭단체" in squash(ctx["post_title"])):
            pm = PARTY_RE.search(squash(dept) + " " + squash(g("purpose")))
            if pm:
                role = "교섭단체 " + pm.group(1)
        wrapped = any("\n" in s for s in str_cells)
        recs.append({
            "source_id": "seoul",
            "council": "서울특별시의회",
            "doc_id": ctx["doc_id"],
            "doc_title": ctx["doc_title"],
            "doc_url": ctx["doc_url"],
            "post_url": ctx["post_url"],
            "period": ctx["period"],
            "row_no": parse_amount(g("row_no")) if not content_fix else content_fix["row_no"],
            "budget_item": budget,
            "budget_item_inferred": inferred,
            "department": norm(g("department")),
            "user_role": role,
            "date": d,
            "time": t,
            "amount": amt,
            "merchant_name": merchant,
            "merchant_address": addr,
            "purpose": norm((norm(g("purpose")) or "") + (spill or "")) if spill else norm(g("purpose")),
            "attendees": parse_attendees(g("attendees")) if not content_fix else content_fix["attendees"],
            "payment_method": canon_payment(norm(g("payment_method")) or (content_fix or {}).get("payment")),
            "parse_confidence": "MEDIUM" if repaired or content_fix or spill or (wrapped and ctx["ext"] == ".pdf" and not merchant) else "HIGH",
            "post_author": ctx["post_author"],
        })
    return recs, skipped, totals


def main():
    manifest = json.loads((RAW_DIR / "manifest.json").read_text(encoding="utf-8"))
    files, records, seen = [], [], {}
    for post in sorted(manifest, key=lambda p: (p.get("period") or "", p.get("posted_date") or "")):
        for att in post["attachments"]:
            entry = {"doc_id": "seoul:" + att["sha256"][:12], "file": att["filename"], "period": post.get("period"),
                     "post_title": post["post_title"]}
            if att["sha256"] in seen:
                files.append({**entry, "status": "skipped", "reason": f"동일 파일이 이전 게시글({seen[att['sha256']]})에 이미 첨부됨"})
                continue
            seen[att["sha256"]] = post["post_title"]
            path = ROOT / att["local_path"]
            ext = path.suffix.lower()
            ctx = {"doc_id": entry["doc_id"], "doc_title": att["filename"], "doc_url": att["url"], "post_url": post["post_url"],
                   "period": post.get("period"), "post_title": post["post_title"], "post_author": post.get("author"),
                   "budget": budget_from_text(att["filename"]) or budget_from_text(post["post_title"]), "ext": ext}
            try:
                if ext == ".pdf":
                    rows, chars = raw_rows_pdf(path)
                    if not rows:
                        files.append({**entry, "status": "unparsed",
                                      "reason": "표를 추출하지 못함" + (" (텍스트 없음: 스캔 이미지로 보임)" if chars < 50 else "")})
                        continue
                    recs, skipped, totals = rows_to_records(rows, ctx)
                    stale = []
                    if not recs:
                        recs = text_fallback(path, ctx)
                        if not recs and pdf_is_image_text(path):
                            files.append({**entry, "status": "unparsed",
                                          "reason": "한글이 이미지로 들어간 PDF(숫자만 텍스트로 추출됨) — 상호·목적은 OCR 필요"})
                            continue
                elif ext in (".xlsx", ".xlsm", ".xls"):
                    per_sheet = [(name, *rows_to_records(rows, ctx)) for name, rows in sheets_xlsx(path)]
                    # 이전 달 시트가 남아 있는 파일: 공개 기간에 맞는 시트가 있으면 기간이 전혀 안 맞는 시트는 제외
                    fits = [x for x in per_sheet if x[1] and any(in_period(r, ctx["period"]) for r in x[1])]
                    keep = fits if fits else per_sheet
                    kept = {id(x) for x in keep}
                    stale = [{"sheet": x[0], "rows": len(x[1]), "dates": [min(r["date"] for r in x[1]), max(r["date"] for r in x[1])]}
                             for x in per_sheet if x[1] and id(x) not in kept]
                    recs = [r for _, rs, _, _ in keep for r in rs]
                    skipped = [k for _, _, ks, _ in keep for k in ks]
                    totals = [t for _, _, _, ts in keep for t in ts]
                else:
                    files.append({**entry, "status": "unparsed", "reason": f"지원하지 않는 형식({ext}) — 수동 확인 필요"})
                    continue
            except Exception as e:  # 손상 파일 등
                files.append({**entry, "status": "unparsed", "reason": f"파싱 오류: {e}"})
                continue
            if not recs:
                if (totals and all(t == 0 for t in totals)) or (ext == ".pdf" and pdf_says_empty(path)) or (ext != ".pdf" and is_blank_template(path)):
                    files.append({**entry, "status": "empty", "reason": "집행 실적 없음(빈 서식, 합계 0)"})
                else:
                    reasons = sorted({k["reason"] for k in skipped})
                    files.append({**entry, "status": "unparsed",
                                  "reason": (", ".join(reasons) + f" — {len(skipped)}행, 수동 확인 필요") if skipped else "집행내역 표를 찾지 못함",
                                  "skipped_sample": skipped[:3]})
                continue
            amount_sum = sum(r["amount"] for r in recs)
            files.append({**entry, "status": "parsed", "rows": len(recs), "amount_sum": amount_sum, "printed_totals": totals,
                          "total_matches": (amount_sum in totals) if totals else None, "rejected_rows": skipped[:10] or None, "rejected_count": len(skipped),
                          "attendees_null": sum(1 for r in recs if r["attendees"] is None),
                          "time_null": sum(1 for r in recs if r["time"] is None),
                          "stale_sheets_skipped": stale or None})
            records.extend(recs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    st = {}
    for x in files:
        st[x["status"]] = st.get(x["status"], 0) + 1
    summary = {"rows": len(records), "files": st,
               "date_min": min((r["date"] for r in records), default=None), "date_max": max((r["date"] for r in records), default=None)}
    REPORT.write_text(json.dumps({"files": files, "summary": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
