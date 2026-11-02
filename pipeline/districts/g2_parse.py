"""G2 구의회 첨부(PDF·XLSX·XLS) → data/staging/<slug>.jsonl

- 표 헤더 이름으로 열을 매핑한다. 헤더가 이미지로 들어간 PDF(동대문 일부)는 값의 모양(날짜·시간·금액·인원)으로 열을 추정한다.
- 사용자 칸이 없거나 읽을 수 없으면 게시글 제목·파일명에서 직책을 정한다. 사람 이름은 쓰지 않는다.
- '집행액(천원)'처럼 단위가 천원인 파일은 값의 크기를 보고 원 단위로 바꾼다(제목만 천원이고 값은 원인 파일이 있다).
- 참석자 명단은 개인 성명이 있어 파싱하지 않는다.
"""
import io
import json
import re
import statistics
import sys
import warnings
from datetime import date, datetime, time, timedelta
from pathlib import Path

import openpyxl
import pdfplumber
import xlrd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import clean_text, period_range  # noqa: E402
from g2_sites import COUNCILS, clean_filename, title_range_end  # noqa: E402

warnings.filterwarnings("ignore")
ROOT = HERE.parent.parent

# (키워드, 필드) — 앞 규칙 우선. '집행대상'은 인원 텍스트일 수 있어 따로 둔다.
HEADER_KEYWORDS = [
    ("연번", "row_no"), ("순번", "row_no"), ("번호", "row_no"),
    ("대상인원", "attendees"), ("집행인원", "attendees"), ("인원", "attendees"),
    ("집행대상", "target"),
    ("사용자", "user_role"), ("집행자", "user_role"),
    ("집행부서", "department"), ("부서", "department"), ("위원회명", "department"),
    ("비목", "budget_item"), ("과목", "budget_item"), ("구분", "budget_item"),
    ("시군구", "merchant_address"),
    ("시간", "time"),
    ("집행일시", "date"), ("사용일시", "date"), ("일시", "date"), ("집행일", "date"), ("사용일", "date"), ("일자", "date"), ("날짜", "date"),
    ("금액", "amount"), ("집행액", "amount"),
    ("가맹점", "merchant_name"), ("상호", "merchant_name"),
    ("집행장소", "merchant_name"), ("사용장소", "merchant_name"), ("장소", "merchant_name"), ("사용처", "merchant_name"),
    ("주소", "merchant_address"), ("소재지", "merchant_address"),
    ("집행목적", "purpose"), ("사용목적", "purpose"), ("목적", "purpose"), ("집행내역", "purpose"), ("사용내역", "purpose"),
    ("내역", "purpose"), ("내용", "purpose"), ("집행유형", "purpose"),
    ("결제", "payment_method"), ("방법", "payment_method"),
]
SUB_LABELS = {"일자", "시간", "상호명", "상호", "주소", "장소"}
DATE_RE = re.compile(r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})|(?<!\d)(20\d{2})(0[1-9]|1[0-2])([0-2]\d|3[01])(?!\d)")
SHORT_DATE_RE = re.compile(r"^(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?")
TIME_RE = re.compile(r"(?<!\d)(\d{1,2})\s*:\s*(\d{2})")
AMOUNT_RE = re.compile(r"^-?[\d,]+(\.\d+)?$")
TOTAL_RE = re.compile(r"^(합\s*계|총\s*계|소\s*계|계|누\s*계)$")
ROLE_TOKEN = re.compile(
    r"(제\s*[12]\s*부의장|부의장|의장단|의장|[가-힣]{2,12}위원장|[가-힣]{2,12}위원회|교섭단체[^,()]*|의회사무국장|사무국장|의회사무국|사무국|"
    r"전문위원|[가-힣]{1,8}팀장|[가-힣]{1,8}담당관|[가-힣]{1,8}담당|운영위원장)")
PAYMENT_WORDS = re.compile(r"카드|현금|계좌|이체|제로페이|국내|법인")


def norm(v):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v).replace("　", " ")).strip()
    return s or None


def squash(v):
    return re.sub(r"\s+", "", str(v or ""))


# ------------------------------------------------------------------ value parsers
def parse_amount(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    s = re.sub(r"[\s,원₩]", "", str(v))
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return int(round(float(s)))
    m = re.fullmatch(r"(-?\d+)(카드|현금|제로페이|계좌이체|이체|계좌)", s)  # 성동: 금액·결제방법 칸 병합 '7,800 카드'
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"\((\d+)\)", s) or re.fullmatch(r"△(\d+)", s)
    return -int(m.group(1)) if m else None


def parse_date(v, period, datemode=None):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 30000 < v < 60000:
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = str(v).strip()
    # 성동 사무국: 집행일 칸에 '일'만 있음 → 공개 대상 월과 합친다
    if re.fullmatch(r"\d{1,2}(\.0)?", s) and period and re.fullmatch(r"\d{4}-\d{2}", period):
        try:
            return date(int(period[:4]), int(period[5:]), int(float(s)))
        except ValueError:
            return "INVALID"
    try:
        m = DATE_RE.search(s)
        if m:
            y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), m.group(5), m.group(6))
            return date(int(y), int(mo), int(d))
        m = SHORT_DATE_RE.match(s)
        if m and period:
            return date(int(period[:4]), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return "INVALID"
    return None


def parse_time(v):
    if v is None:
        return None
    if isinstance(v, (time, datetime)):
        return f"{v.hour:02d}:{v.minute:02d}" if not (isinstance(v, datetime) and v.hour == 0 and v.minute == 0) else None
    if isinstance(v, float) and 0 < v < 1:
        mins = round(v * 1440)
        return f"{mins // 60:02d}:{mins % 60:02d}"
    s = str(v)
    m = TIME_RE.search(s)
    if m and int(m.group(1)) < 24:
        h = int(m.group(1))
        if "오후" in s and h < 12:
            h += 12
        return f"{h:02d}:{m.group(2)}"
    return None


def parse_attendees(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if 0 < v < 10000 else None
    s = str(v)
    m = re.search(r"외\s*(\d+)\s*(명|인)", s)
    if m:
        return int(m.group(1)) + 1
    m = re.search(r"(\d+)\s*(명|인)", s) or re.fullmatch(r"\s*(\d+)\s*", s)
    return int(m.group(1)) if m and 0 < int(m.group(1)) < 10000 else None


def canon_budget(s):
    t = squash(s)
    if not t:
        return None
    if "공통" in t or t == "의정운영":
        return "의정운영공통경비"
    if "교섭" in t:
        return "의정운영공통경비"
    if "의회운영" in t or t in ("의회", "운영"):
        return "의회운영업무추진비"
    if "시책" in t:
        return "시책추진업무추진비"
    if "기관" in t:
        return "기관운영업무추진비"
    if "부서" in t or "정원가산" in t:
        return "부서운영업무추진비"
    return norm(s)


def budget_from_text(*texts):
    t = squash(" ".join(x or "" for x in texts))
    if "공통경비" in t or "교섭단체" in t:
        return "의정운영공통경비"
    if "의회운영" in t or "의장" in t or "위원장" in t:
        return "의회운영업무추진비"
    if "시책" in t:
        return "시책추진업무추진비"
    if "기관운영" in t:
        return "기관운영업무추진비"
    if "사무국" in t:
        return "시책추진업무추진비"
    return None


def role_from_text(*texts):
    """제목·파일명에서 직책. 여러 직책이 섞인 게시글이면 None."""
    t = " ".join(x or "" for x in texts)
    t = re.sub(r"의장\s*,\s*부의장\s*및\s*상임위원장|의장단\(상임위원장\s*포함\)", "의장단", t)
    roles = []
    for m in ROLE_TOKEN.finditer(t):
        r = re.sub(r"\s+", "", m.group(1))
        if r in ("의회운영업무추진비",) or r.endswith("업무추진비"):
            continue
        roles.append(r)
    roles = [r for r in roles if r not in ("의회사무국",) or len(roles) == 1]
    uniq = list(dict.fromkeys(roles))
    if len(uniq) == 1:
        return uniq[0]
    if "의장단" in uniq:
        return "의장단"
    return None


NAME_LIKE = re.compile(r"^[가-힣]{2,4}$")
ROLE_WORDS = re.compile(r"의장|위원|사무|팀|과$|국|관|담당|교섭|의회|실$|비서")


def clean_role(cell, fallback):
    """사용자 칸 정리: 직책 단어만 남기고, 사람 이름으로 보이면 버린다."""
    s = norm(cell)
    if not s:
        return fallback, False
    s = re.sub(r"(?<=[가-힣])\s+(?=[가-힣])", "", s) if len(s) <= 20 else s
    m = ROLE_TOKEN.search(s)
    if m:
        return re.sub(r"\s+", "", m.group(1)), False
    if NAME_LIKE.match(s.replace(" ", "")) and not ROLE_WORDS.search(s):
        return fallback, True  # 사람 이름으로 보임 → 쓰지 않음
    return s, False


# ------------------------------------------------------------------ table extraction
def sniff(data, filename):
    if data[:4] == b"%PDF":
        return "pdf"
    if data[:2] == b"PK":
        return "xlsx" if b"xl/" in data[:4000] or filename.lower().endswith((".xlsx", ".xlsm")) else "zip"
    if data[:4] == b"\xd0\xcf\x11\xe0":
        return "hwp" if filename.lower().endswith(".hwp") else "xls"
    if data[:16].lstrip().lower().startswith((b"<html", b"<!doc", b"<table")):
        return "html"
    return "other"


def tables_xlsx(data):
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    out = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        for rng in ws.merged_cells.ranges:  # 병합 셀 값 채우기(세로 병합된 사용자·비목)
            v = ws.cell(rng.min_row, rng.min_col).value
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    if r - 1 < len(grid) and c - 1 < len(grid[r - 1]) and grid[r - 1][c - 1] is None and rng.max_row > rng.min_row:
                        grid[r - 1][c - 1] = v
        out.append(grid)
    return out


def tables_xls(data):
    wb = xlrd.open_workbook(file_contents=data, formatting_info=False)
    out = []
    for sh in wb.sheets():
        grid = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                v = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        v = xlrd.xldate_as_datetime(v, wb.datemode)
                    except Exception:
                        pass
                elif cell.ctype == xlrd.XL_CELL_EMPTY or v == "":
                    v = None
                row.append(v)
            grid.append(row)
        out.append(grid)
    return out


LOW_MARK = "__LOW_CONFIDENCE__"


def explode_stacked_row(cells):
    """글자가 겹쳐 인쇄된 PDF: 표 전체가 한 행으로 뭉쳐 각 칸에 '헤더\n값1\n값2…'로 들어온다.
    줄 수가 맞는 열(날짜·금액·인원·결제방법)만 살리고, 줄 수가 어긋난(겹친 글자) 열은 비운다."""
    parts = [c.split("\n") if c else [] for c in cells]
    if sum(len(p) >= 4 for p in parts) < 3 or header_score([p[0] if p else None for p in parts]) < 3:
        return None
    n = max(len(p) for p in parts) - 1
    out = [[p[0] if p else None for p in parts]]
    for i in range(1, n + 1):
        out.append([(p[i] if len(p) - 1 == n else None) for p in parts] + [LOW_MARK])
    return out


def tables_pdf(data):
    rows, text_chars = [], 0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            text_chars += len((pg.extract_text() or "").strip())
            for t in pg.extract_tables():
                for r in t:
                    cells = [None if c is None else str(c) for c in r]  # 줄바꿈 유지: 병합된 금액 칸 복구에 필요
                    rows.extend(explode_stacked_row(cells) or [cells])
    return [rows], text_chars


# ------------------------------------------------------------------ header mapping
def header_score(row):
    cells = [squash(c) for c in row if c is not None and str(c).strip()]
    hits = 0
    for c in cells:
        if len(c) > 14:
            continue
        if any(k in c for k, _ in HEADER_KEYWORDS):
            hits += 1
    return hits


def map_header(row, sub=None):
    mapping, used = {}, set()
    for j, cell in enumerate(row):
        top = squash(cell)
        s = squash(sub[j]) if sub and j < len(sub) else ""
        label = s if s in SUB_LABELS or (s and not top) else top
        if s == "주소":
            field = "merchant_address"
        elif s in ("상호명", "상호", "장소"):
            field = "merchant_name"
        elif s == "일자":
            field = "date"
        elif s == "시간":
            field = "time"
        else:
            field = next((f for k, f in HEADER_KEYWORDS if k in label), None) if label and len(label) <= 14 else None
        if not field:
            continue
        if field in used:
            if field == "date" and "time" not in used and ("일시" in label or "시간" in label):
                field = "time"  # 도봉: '사용일'(날짜) + '사용일시'(1970-01-01 13:06 형식의 시각)
            elif field == "purpose" and "payment_method" not in used and "유형" in label:
                field = "payment_method"  # 서대문: '집행유형'이 두 번(목적, 결제방법)
            elif field == "merchant_name" and "merchant_alt" not in used:
                field = "merchant_alt"  # 송파: '사용처'(직책)와 '장소'(상호)
            else:
                continue
        mapping[field] = j
        mapping.setdefault("_labels", {})[field] = label
        used.add(field)
    return mapping


def infer_mapping(rows):
    """헤더가 없거나 이미지인 표: 값 모양으로 열을 추정."""
    sample = [r for r in rows if any(DATE_RE.search(str(c or "")) for c in r)][:15]
    if len(sample) < 2:
        return None
    ncol = max(len(r) for r in sample)
    kinds = {}
    for j in range(ncol):
        vals = [str(r[j]).strip() for r in sample if j < len(r) and r[j] not in (None, "")]
        if not vals:
            continue
        if sum(bool(DATE_RE.search(v)) for v in vals) >= len(vals) * 0.8:
            kinds.setdefault("date", j)
        elif sum(bool(re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", v)) for v in vals) >= len(vals) * 0.8:
            kinds.setdefault("time", j)
        elif sum(bool(re.fullmatch(r"-?\d{1,3}(,\d{3})+|-?\d{4,}", v)) for v in vals) >= len(vals) * 0.8:
            kinds.setdefault("amount", j)
        elif sum(bool(re.fullmatch(r"\d{1,3}", v)) for v in vals) >= len(vals) * 0.8 and "amount" in kinds:
            kinds.setdefault("attendees", j)
        elif sum(bool(PAYMENT_WORDS.fullmatch(v)) for v in vals) >= len(vals) * 0.8:
            kinds.setdefault("payment_method", j)
        elif "amount" in kinds and "merchant_name" not in kinds:
            kinds["merchant_name"] = j
        elif "merchant_name" in kinds and "purpose" not in kinds:
            kinds["purpose"] = j
    if "date" in kinds and "amount" in kinds:
        kinds["_inferred"] = True
        return kinds
    return None


# ------------------------------------------------------------------ rows → records
def records_from_grid(grid, ctx, allow_infer=True):
    recs, mapping, i, scale, problems = [], None, 0, 1, []
    role_col_values = None
    while i < len(grid):
        row = grid[i]
        if header_score(row) >= 3:
            sub = grid[i + 1] if i + 1 < len(grid) else None
            has_sub = sub is not None and sum(squash(c) in SUB_LABELS for c in sub if c) >= 1 and not any(
                DATE_RE.search(str(c or "")) for c in sub)
            new_map = map_header(row, sub if has_sub else None)
            if "amount" in new_map and "date" in new_map:
                mapping = new_map
                labels = mapping.get("_labels", {})
                scale = 1000 if "천원" in (labels.get("amount") or "") else 1
            i += 2 if has_sub else 1
            continue
        if mapping is None:
            i += 1
            continue
        recs.append((row, mapping, scale))
        i += 1
    if not recs and allow_infer:
        inferred = infer_mapping(grid)
        if inferred:
            recs = [(r, inferred, 1) for r in grid]
    repaired = repair_merged_amounts(recs)
    out = []
    for idx, (row, mp, sc) in enumerate(recs):
        g = lambda k: row[mp[k]] if k in mp and mp[k] < len(row) else None
        first = squash(row[0]) if row else ""
        if TOTAL_RE.match(first) or any(TOTAL_RE.match(squash(c)) for c in row[:3] if c):
            continue
        d = parse_date(g("date"), ctx["period"])
        amount = parse_amount(g("amount"))
        if d == "INVALID":
            problems.append("날짜 형식 오류 행 제외")
            continue
        if d is None or amount is None or amount == 0 and not g("merchant_name"):
            continue
        out.append({"row": row, "mp": mp, "scale": sc, "date": d, "amount": amount, "repaired": idx in repaired, "g": {k: g(k) for k in (
            "row_no", "attendees", "target", "user_role", "department", "budget_item", "merchant_address", "time",
            "merchant_name", "merchant_alt", "purpose", "payment_method")}, "datetime_raw": g("date")})
    return out, problems


NUM_TOKEN = re.compile(r"-?\d{1,3}(?:,\d{3})+|-?\d+")


def repair_merged_amounts(recs):
    """PDF 표 추출에서 다음 행의 금액이 윗 칸에 줄바꿈으로 붙는 경우: '45,000\n120,000' + 다음 행 빈칸 → 나눠 넣는다."""
    repaired = set()
    for i, (row, mp, sc) in enumerate(recs):
        j = mp.get("amount")
        if j is None or j >= len(row) or not isinstance(row[j], str) or "\n" not in row[j]:
            continue
        toks = [t for t in (x.strip() for x in row[j].split("\n")) if NUM_TOKEN.fullmatch(t.replace(" ", ""))]
        if len(toks) < 2:
            continue
        nxt = [k for k in range(i + 1, min(len(recs), i + len(toks))) if recs[k][1].get("amount") == j]
        empties = [k for k in nxt if recs[k][0][j] in (None, "")]
        if len(empties) == len(toks) - 1:
            row[j] = toks[0]
            repaired.add(i)
            for k, t in zip(empties, toks[1:]):
                recs[k][0][j] = t
                repaired.add(k)
    return repaired


def decide_scale(parsed, problems):
    """헤더가 '천원'이어도 값이 원 단위인 시트가 있다 — 남은 행의 중앙값으로 시트별 판정."""
    if not parsed or not any(r["scale"] == 1000 for r in parsed):
        return
    med = statistics.median(abs(r["amount"]) for r in parsed if r["amount"]) if any(r["amount"] for r in parsed) else 0
    if med >= 5000:
        for r in parsed:
            r["scale"] = 1
        problems.append("헤더는 천원이지만 값이 원 단위 → 변환 안 함")
    else:
        problems.append("천원 단위 → 원으로 변환")


def enrich_from_logs(parsed, logs):
    """서대문: 본 시트에 상호·시간이 없고, 같은 파일의 카드 승인 내역 시트에 있다. (날짜, 금액)이 하나로만 맞을 때만 연결."""
    want = {}
    for p in parsed:
        want.setdefault((p["date"], p["amount"] * p["scale"]), []).append(p)
    filled = 0
    for grid in logs:
        rows = [r for r in grid if any(isinstance(c, (date, datetime)) or DATE_RE.search(str(c or "")) for c in r)]
        if len(rows) < 2:
            continue
        ncol = max(len(r) for r in rows)
        colvals = lambda j: [r[j] if j < len(r) else None for r in rows]
        dcol = next((j for j in range(ncol) if sum(isinstance(parse_date(v, None), date) for v in colvals(j)) >= len(rows) * 0.8), None)
        if dcol is None:
            continue
        thousand = any(p["scale"] == 1000 for p in parsed)

        def keys(d, amt):
            """본 시트가 천원 단위(반올림·절사)면 승인 금액도 천원으로 맞춰 비교."""
            if amt is None:
                return []
            if not thousand:
                return [(d, amt)]
            return list({(d, round(amt / 1000) * 1000), (d, (amt // 1000) * 1000)})

        best, best_hits = None, 0
        for j in range(ncol):
            if j == dcol:
                continue
            hits = sum(any(k in want for k in keys(parse_date(r[dcol], None), parse_amount(r[j]))) for r in rows if j < len(r))
            if hits > best_hits:
                best, best_hits = j, hits
        if best is None or best_hits < len(rows) * 0.3:
            continue
        tcol = next((j for j in range(ncol) if sum(bool(re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", str(v or "").strip())) for v in colvals(j)) >= len(rows) * 0.8), None)
        mcol = max((j for j in range(ncol) if j not in (dcol, best, tcol)),
                   key=lambda j: sum(bool(re.search(r"[가-힣A-Za-z]{2,}", str(v or ""))) and "*" not in str(v or "") for v in colvals(j)), default=None)
        index = {}
        for r in rows:
            for key in keys(parse_date(r[dcol], None), parse_amount(r[best]) if best < len(r) else None):
                index.setdefault(key, []).append(r)
        for key, cands in index.items():
            targets = want.get(key, [])
            if len(cands) == 1 and len(targets) == 1:
                p, r = targets[0], cands[0]
                if p.get("enriched"):
                    continue
                g = p["g"]
                if not g["merchant_name"] and mcol is not None and mcol < len(r) and r[mcol]:
                    g["merchant_name"] = r[mcol]
                    p["enriched"] = True
                if not g["time"] and tcol is not None and tcol < len(r) and r[tcol]:
                    g["time"] = r[tcol]
                exact = parse_amount(r[best])
                if p["enriched"] and exact:
                    p["amount"], p["scale"] = exact, 1  # 승인 내역의 원 단위 정확한 금액
                filled += 1 if p.get("enriched") else 0
    return filled


def fingerprint(p):
    g = p["g"]
    return (p["date"].isoformat(), p["amount"], squash(g["user_role"]), squash(g["purpose"]), squash(g["target"]),
            squash(g["attendees"]), squash(g["merchant_name"]))


def out_of_period(d, period):
    if not period:
        return False
    s, e = period_range(period)
    return not (date.fromisoformat(s) - timedelta(days=31) <= d <= date.fromisoformat(e) + timedelta(days=31))


def to_rows(parsed, ctx, slug, att, post):
    c = COUNCILS[slug]
    out = []
    title_role = ctx["title_role"]
    # 송파처럼 '사용처' 열에 직책이 들어 있는 경우
    merch_vals = [norm(p["g"]["merchant_name"]) for p in parsed if p["g"]["merchant_name"]]
    merchant_is_role = merch_vals and sum(bool(ROLE_TOKEN.fullmatch(v.replace(" ", ""))) for v in merch_vals) >= len(merch_vals) * 0.7
    for n, p in enumerate(parsed):
        g, mp = p["g"], p["mp"]
        conf = "MEDIUM" if mp.get("_inferred") or p.get("repaired") or p.get("enriched") else "HIGH"
        if p["row"] and p["row"][-1] == LOW_MARK:
            conf = "LOW"
        merchant, address, role_cell = g["merchant_name"], g["merchant_address"], g["user_role"]
        if merchant_is_role:
            role_cell, merchant = merchant, g["merchant_alt"]
        elif not merchant and g["merchant_alt"]:
            merchant = g["merchant_alt"]
        bi_raw = g["budget_item"]
        if bi_raw and ROLE_TOKEN.fullmatch(squash(bi_raw)) and not canon_budget(bi_raw).endswith(("업무추진비", "공통경비")):
            role_cell, bi_raw = role_cell or bi_raw, None  # 도봉: '구분' 열에 직책
        if role_cell is None and g["department"]:
            role_cell = g["department"]
        role, was_name = clean_role(role_cell, title_role)
        if was_name or (role_cell is None and title_role):
            conf = "MEDIUM" if conf == "HIGH" else conf
        bi = canon_budget(bi_raw)
        inferred = False
        if not bi:
            inferred = True
            t = squash(post["post_title"] + " " + att["filename"])
            mixed = "공통경비" in t and "의회운영" in t  # 도봉: 한 파일에 직책별 업무추진비 + 공통경비 시트
            if mixed and role and re.search(r"(^|[^회])의장$|부의장$|위원장$|원내대표$|대표의원$", role):
                bi = "의회운영업무추진비"
            else:
                bi = budget_from_text(post["post_title"], att["filename"])
        if role is None and mp.get("_inferred") and bi == "의회운영업무추진비":
            role = "의장단(사용자 판독 불가)"  # 동대문: 사용자 열이 이미지로 들어가 읽을 수 없음
        tm = parse_time(g["time"]) or parse_time(p["datetime_raw"] if not isinstance(p["datetime_raw"], date) else None)
        if isinstance(p["datetime_raw"], datetime) and not tm:
            tm = parse_time(p["datetime_raw"])
        att_n = parse_attendees(g["attendees"])
        if att_n is None and g["target"]:
            att_n = parse_attendees(g["target"])
        merchant = norm(merchant)
        if address is None and merchant and re.search(r"(서울특별시|서울)\s?[가-힣]+구\s", merchant + " "):
            m = re.search(r"(서울특별시|서울)\s?[가-힣]+구\s", merchant + " ")
            if m.start() >= 2:
                merchant, address = merchant[:m.start()].strip(), merchant[m.start():].strip()
        if not merchant:
            conf = "MEDIUM" if conf == "HIGH" else conf
        rn = parse_amount(g["row_no"])
        out.append({
            "source_id": slug,
            "council": c["name"],
            "doc_id": f"{slug}:{att['sha256'][:12]}",
            "doc_title": clean_filename(att["filename"]),
            "doc_url": att["url"],
            "post_url": post["post_url"],
            "period": post["period"],
            "row_no": rn if rn is not None and 0 < rn < 100000 else n + 1,
            "budget_item": bi,
            "budget_item_inferred": inferred,
            "department": norm(g["department"]),
            "user_role": role,
            "date": p["date"].isoformat(),
            "time": tm,
            "amount": p["amount"] * p["scale"],
            "merchant_name": merchant,
            "merchant_address": norm(address),
            "purpose": norm(g["purpose"]),
            "attendees": att_n,
            "payment_method": norm(g["payment_method"]),
            "parse_confidence": conf,
        })
    return out


def parse_file(path, slug, att, post, seen_fp):
    data = path.read_bytes()
    kind = sniff(data, att["filename"])
    # 파일명이 직책별(서초: '…의장 업무추진비.pdf')이면 파일명을, 아니면 게시글 제목을 쓴다
    fname_role = role_from_text(re.sub(r"\.\w+$", "", clean_filename(att["filename"])))
    ctx = {"period": post["period"], "title_role": fname_role or role_from_text(post["post_title"])}
    if kind == "pdf":
        grids, chars = tables_pdf(data)
        if chars < 20:
            return [], "unparsed", "텍스트가 없는 이미지 PDF (OCR 필요)"
    elif kind == "xlsx":
        grids = tables_xlsx(data)
    elif kind == "xls":
        try:
            grids = tables_xls(data)
        except Exception as e:
            return [], "unparsed", f"XLS 읽기 실패: {e}"
    elif kind == "hwp":
        return [], "unparsed", "HWP 형식 (자동 파싱 미지원)"
    else:
        return [], "unparsed", f"지원하지 않는 형식({kind})"
    rows, problems, stale, new_fp, kept_all, logs = [], [], 0, set(), [], []
    # 헤더가 있는 표가 하나라도 있으면, 헤더 없는 시트(카드 승인 로그 등 같은 거래의 다른 표현)는 값 추정으로 읽지 않는다
    has_header = any(records_from_grid(g, ctx, allow_infer=False)[0] for g in grids)
    skipped_sheets = 0
    for grid in grids:
        parsed, pr = records_from_grid(grid, ctx, allow_infer=not has_header)
        if not parsed and has_header and any(DATE_RE.search(str(c or "")) for r in grid for c in r):
            skipped_sheets += 1
        kept = []
        for p in parsed:
            fp = fingerprint(p)
            # 이전 파일에 이미 있던 행이 기간 밖 날짜로 다시 실린 경우(지난 달 서식을 재사용하며 남은 행) 제외
            if fp in seen_fp and out_of_period(p["date"], post["period"]):
                stale += 1
                continue
            new_fp.add(fp)
            kept.append(p)
        decide_scale(kept, pr)
        problems += pr
        kept_all.extend(kept)
        if not parsed and has_header:
            logs.append(grid)
    if kept_all and logs:
        n = enrich_from_logs(kept_all, logs)
        if n:
            problems.append(f"카드 승인 내역 시트에서 상호·시간 {n}건 연결(날짜·금액 일치)")
    rows += to_rows(kept_all, ctx, slug, att, post)
    seen_fp |= new_fp
    if skipped_sheets:
        problems.append(f"헤더 없는 보조 시트 {skipped_sheets}개 제외(같은 거래의 카드 승인 내역 등)")
    if stale:
        problems.append(f"이전 파일과 같은 기간 밖 행 {stale}개 제외(서식 재사용 잔여)")
    if not rows:
        return [], "unparsed", "집행내역 표를 찾지 못함" + (f" ({'; '.join(sorted(set(problems)))})" if problems else "")
    return rows, "parsed", "; ".join(sorted(set(problems))) or None


def parse_council(slug):
    mpath = ROOT / "data" / "raw" / slug / "manifest.json"
    if not mpath.exists():
        print(f"[{slug}] no manifest", file=sys.stderr)
        return
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    rows, files, seen, seen_fp = [], [], {}, set()
    for post in sorted(manifest, key=lambda p: (p.get("period") or "", p.get("posted_date") or "")):
        for att in post["attachments"]:
            fname = clean_filename(att["filename"])
            entry = {"file": fname, "period": post["period"], "post_title": post["post_title"], "sha256": att["sha256"]}
            rng = title_range_end(post["post_title"])
            if rng and rng < (2022, 7):
                entry.update(status="skipped", rows=0, amount_sum=0, reason="수집 범위(2022-07 이후) 이전 공개분")
            elif "명단" in fname or "명단" in post["post_title"]:
                entry.update(status="skipped", rows=0, amount_sum=0, reason="참석자 명단(개인 성명 포함) — 파싱 대상 아님")
            elif att["sha256"] in seen:
                entry.update(status="skipped", rows=0, amount_sum=0, reason=f"동일 파일이 이전 게시글({seen[att['sha256']]})에 이미 첨부됨")
            else:
                try:
                    got, status, reason = parse_file(ROOT / att["local_path"], slug, att, post, seen_fp)
                except Exception as e:  # 손상 파일
                    got, status, reason = [], "unparsed", f"파싱 오류: {type(e).__name__}: {e}"
                entry.update(status=status, rows=len(got), amount_sum=sum(r["amount"] for r in got), reason=reason)
                rows += got
            seen.setdefault(att["sha256"], post["post_title"])
            files.append(entry)
    out = ROOT / "data" / "staging" / f"{slug}.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (ROOT / "data" / "staging" / f"{slug}_parse_report.json").write_text(
        json.dumps({"files": files}, ensure_ascii=False, indent=1), encoding="utf-8")
    st = {}
    for e in files:
        st[e["status"]] = st.get(e["status"], 0) + 1
    dates = sorted(r["date"] for r in rows)
    print(f"[{slug}] rows={len(rows)} files={st} range={dates[0] if dates else '-'}~{dates[-1] if dates else '-'}", file=sys.stderr)
    write_registry(slug, manifest, rows, files)


def write_registry(slug, manifest, rows, files):
    c = COUNCILS[slug]
    ranges = [period_range(p["period"]) for p in manifest
              if p.get("period") and not (title_range_end(p["post_title"]) and title_range_end(p["post_title"]) < (2022, 7))]
    starts, ends = sorted(r[0] for r in ranges), sorted(r[1] for r in ranges)
    fmts = sorted({(clean_filename(a["filename"]).rsplit(".", 1)[-1].lower() if "." in a["filename"] else "?")
                   for p in manifest for a in p["attachments"]})
    has = lambda k: round(sum(1 for r in rows if r.get(k)) / len(rows), 3) if rows else 0
    reg = {
        "source_id": slug, "name": c["name"], "region": c["region"], "board_url": c["base"] + c["list"],
        "term_base_2018": 8, "formats": fmts,
        "collected_from": starts[0][:7] if starts else None, "collected_to": ends[-1][:7] if ends else None,
        "rows": len(rows), "posts": len(manifest), "files": len(files),
        "field_coverage": {"time": has("time"), "merchant_address": has("merchant_address"), "attendees": has("attendees"),
                           "user_role": has("user_role")},
        "notes": REGISTRY_NOTES.get(slug, ""),
    }
    d = ROOT / "data" / "staging" / "councils"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


REGISTRY_NOTES = {
    "dobong": "XLSX. 의원 직책별 시트(의장·부의장·위원장·예결위원장) + 의정운영공통경비 시트가 한 파일(분기별)에, 의회사무국은 월별. "
              "'구분' 열에 직책이 들어 있어 사용자로 사용. 시간은 '사용일시' 열(1970-01-01 HH:MM 형식). 원본 오기로 2013·1900·2052년 날짜 3행 있음.",
    "dongdaemun": "PDF. 게시판에는 2025-06 이후 의회운영업무추진비만 있음(공통경비·사무국 경비 게시판 없음). "
                  "일부 파일은 헤더·사용자 열이 이미지로 들어가 값 모양으로 열을 추정했고 사용자는 '의장단(사용자 판독 불가)'.",
    "dongjak": "PDF. '시군구' 열(거래처 소재 시군구)이 있어 주소로 사용. 교섭단체 운영경비(공통경비) 게시글 별도.",
    "seodaemun": "XLS/XLSX(파일명에 '(0Byte)' 표기가 붙지만 실제 파일 정상). 2024년 이전 의장단 파일은 상호·시간 없이 '집행액(천원)'으로만 공개 — "
                 "천원 단위는 원으로 환산(시트별 판정, 헤더만 천원이고 값은 원인 시트 있음). 2022-08 파일은 카드 승인 내역 시트와 날짜·금액이 하나로 맞을 때만 상호·시간·원단위 금액 연결. "
                 "월별 파일에 2023-01 데이터가 서식 잔여물로 반복 포함되어 이전 파일과 같은 기간 밖 행은 제외. 상호 보유율 약 42%.",
    "seocho": "PDF. 직책별 파일(의장·부의장·운영/행정복지/재정건설위원장)이라 사용자는 파일명에서. 주소 없음.",
    "songpa": "PDF. 게시판이 2024-11부터만 존재. '사용처' 열에 직책, '장소' 열에 상호가 들어 있음. 결제방법 값이 '국내'.",
    "seongdong": "PDF. 분기 단위 공개(의회운영·공통경비)와 월 단위 사무국 공개 혼재. 사무국 일부 파일은 '집행일'에 일(日)만 있어 공개 대상 월과 합침. "
                 "2023-12 사무국 파일은 글자가 겹쳐 인쇄되어 날짜·금액·인원·결제방법만 복구(상호·목적 없음, LOW).",
    "seongbuk": "PDF. 주소·시간·인원 모두 공개. 표 추출 시 다음 행 금액이 윗 칸에 붙는 경우를 복구(MEDIUM).",
}
