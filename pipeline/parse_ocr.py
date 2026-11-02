"""스캔·이미지 PDF를 OCR로 읽어 표를 다시 짠다 → data/staging/<slug>_ocr.jsonl

대상: 각 의회 파싱 보고서에서 'OCR 필요'로 남은 파일.
방법
  1) 페이지 전체 OCR(ocr.py) → 머리글 행에서 열 위치(앵커)를 잡는다. 머리글이 한 상자로 붙어 읽혀도 글자 위치로 나눈다.
  2) 글자 상자를 세로 위치로 묶어 행을 만들고, 날짜·시간·금액·결제수단은 모양으로, 나머지는 가장 가까운 열로 배정한다.
  3) 한 자리 숫자(대상 인원)는 전체 OCR에서 잘 빠지므로, 그 열만 잘라 2배로 키워 다시 OCR한다.
  4) 표의 '합계' 행이 있으면 읽은 금액 합계와 비교해 파일별 일치 여부를 보고서에 남긴다.
OCR로 읽은 행은 parse_confidence를 MEDIUM/LOW로만 두고, 사이트에 'OCR' 표시가 붙는다.
"""
import json
import re
import sys
from datetime import date

import pypdfium2 as pdfium

from common import RAW, ROOT, STAGING, clean_text, write_jsonl
from ocr import ocr_image, ocr_pdf

OCR_REASON = re.compile(r"OCR|스캔|이미지|외곽선|도형|글자 데이터 없음")

HEADER = {
    "row_no": ("연번", "순번", "번호", "No."),
    "budget_item": ("비목", "예산과목"),
    "department": ("집행부서", "부서명", "부서"),
    "user_role": ("사용자", "직책", "집행자"),
    "date": ("집행일자", "사용일자", "집행일시", "사용일시", "승인일자", "승인일", "사용일", "집행일", "일자", "일시", "날짜"),
    "time": ("집행시간", "사용시간", "승인시각", "승인시간", "시각", "시간"),
    "merchant_name": ("상호명", "가맹점명", "상호", "집행장소", "사용장소", "장소", "사용처", "가맹점"),
    "merchant_address": ("주소", "소재지"),
    "purpose": ("집행목적", "집행내역", "사용내역", "사용목적", "목적", "내역", "용도"),
    "attendees": ("대상인원", "참석인원", "인원", "대상"),
    "amount": ("집행금액", "사용금액", "승인금액", "집행액", "금액"),
    "payment_method": ("결제방법", "결제수단", "결제", "방법"),
    "_biztype": ("업종명", "업종"),
}
TEXT_COLS = ("department", "user_role", "merchant_name", "merchant_address", "purpose", "budget_item", "_biztype")
# 사용자 칸에는 직책·위원회만 남긴다 (서울시의회 일부 서식은 '김OO 위원장 등 9명'처럼 성명을 적는다)
ROLE_PATTERN = re.compile(r"(제\d)?부?의장|[가-힣]*위원장|[가-힣]*위원회|교섭단체\S*|의회사무국|의회사무처|사무국장|[가-힣]*(담당관|팀장|과장|국장|전문위원)")

DATE_FULL = re.compile(r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")
DATE_SHORT = re.compile(r"(?<!\d)(1[89]|2\d)\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})(?!\d)")  # 2자리 연도는 2018~2029만
DATE_MD = re.compile(r"(?<!\d)(\d{1,2})\s*[-./월]\s*(\d{1,2})(?!\d)")
TIME = re.compile(r"^(\d{1,2})\s*[:;]\s*(\d{2})(\s*[:;]\s*\d{2})?$")  # '.'은 날짜(24.10.02)와 헷갈려 받지 않는다
AMOUNT = re.compile(r"^-?\d{1,3}([,.]\d{3})+(원)?$|^-?\d{4,9}(원)?$")  # OCR이 쉼표를 마침표로 읽기도 한다
PAYMENT = re.compile(r"^(신용카드|체크카드|법인카드|카드|현금|계좌이체|계좌|제로페이|지역화폐|이체)$")
SIDO = re.compile(r"^(서울|경기|인천|부산|대구|광주|대전|울산|세종|강원|충북|충남|전북|전남|경북|경남|제주)")


def header_anchors(boxes):
    """머리글 후보 행(키워드가 가장 많이 겹치는 가로 띠)에서 열 이름 → x 중심.
    '대상인원 집행금액 결제방법'처럼 붙어 읽히거나 '집 행목적'처럼 띄어 읽힌 머리글도 공백을 지우고 찾는다."""
    keys = sorted(((k, col) for col, ks in HEADER.items() for k in ks), key=lambda kc: -len(kc[0]))
    best, best_y = {}, None
    for b in boxes:
        if not any(k in b["text"].replace(" ", "") for k, _ in keys):
            continue
        band = [o for o in boxes if abs((o["y"] + o["h"] / 2) - (b["y"] + b["h"] / 2)) < max(b["h"], 0.006) * 0.9]
        anchors, hit_bottom = {}, b["y"] + b["h"]
        for o in band:
            text = o["text"]
            idx = [i for i, ch in enumerate(text) if ch != " "]
            compact = "".join(text[i] for i in idx)
            used = [False] * len(compact)
            for k, col in keys:
                if col in anchors:
                    continue
                pos = compact.find(k)
                while pos >= 0 and any(used[pos:pos + len(k)]):
                    pos = compact.find(k, pos + 1)
                if pos < 0:
                    continue
                for i in range(pos, pos + len(k)):
                    used[i] = True
                mid = (idx[pos] + idx[pos + len(k) - 1] + 1) / 2 / max(len(text), 1)
                anchors[col] = o["x"] + o["w"] * mid
                hit_bottom = max(hit_bottom, o["y"] + o["h"])
        # OCR 오독(예: '장소'→'잠소', '사용장소'→'사용정소') — 같은 길이에서 한 글자만 다르면 같은 머리글로 본다
        for o in band:
            for tok in re.findall(r"[가-힣]{2,}", o["text"]):
                for k, col in keys:
                    if col in anchors or len(k) != len(tok) or len(k) < 2 or (len(k) == 2 and o["text"].strip() != tok):
                        continue
                    if any(kk == tok for kk, _ in keys):
                        break  # 이미 정확히 일치하는 머리글('장소')은 다른 열('주소')로 다시 잡지 않는다
                    if sum(a != c for a, c in zip(k, tok)) == 1:
                        pos = o["text"].find(tok)
                        anchors[col] = o["x"] + o["w"] * (pos + len(tok) / 2) / max(len(o["text"]), 1)
                        hit_bottom = max(hit_bottom, o["y"] + o["h"])
                        break
        if len(anchors) > len(best):
            best, best_y = anchors, hit_bottom
    return (best, best_y) if len(best) >= 4 and "amount" in best else ({}, None)


SPECIAL = re.compile(r"-?\d{1,3}(?:[,.]\d{3})+원?|\d{1,2}:\d{2}(?::\d{2})?|20\d{2}[-.]\d{1,2}[-.]\d{1,2}|\d+\s*명|신용카드|체크카드|법인카드|카드|현금|계좌이체|제로페이")


def _piece(b, a, z):
    text = b["text"]
    return dict(b, text=text[a:z].strip(), x=b["x"] + b["w"] * a / len(text), w=b["w"] * (z - a) / len(text))


def split_box(b):
    """표 테두리('|')나, 금액·시간·날짜·'N명'·결제수단이 다른 글자와 한 상자로 붙어 읽힌 경우 조각으로 나눈다.
    각 조각의 x는 상자 안 글자 위치로 추정한다."""
    if "|" in b["text"]:
        out, last = [], 0
        for i, ch in enumerate(b["text"] + "|"):
            if ch == "|":
                if b["text"][last:i].strip():
                    out.extend(split_box(_piece(b, last, i)))
                last = i + 1
        return out
    text = b["text"]
    lead = re.match(r"^(\d{1,2})\s+(?=[가-힣A-Za-z(])", text)
    if lead:  # '6 소양강마차' — 인원 칸 숫자가 상호와 붙어 읽힌 경우
        return [_piece(b, 0, len(lead.group(1)))] + split_box(_piece(b, lead.end(), len(text)))
    parts, last = [], 0
    for m in SPECIAL.finditer(text):
        if m.start() == 0 and m.end() == len(text):
            return [b]
        if text[last:m.start()].strip():
            parts.append((last, m.start()))
        parts.append((m.start(), m.end()))
        last = m.end()
    if not parts:
        return [b]
    if text[last:].strip():
        parts.append((last, len(text)))
    return [_piece(b, a, z) for a, z in parts if text[a:z].strip()]


def split_across_columns(b, anchors):
    """한 상자가 글자 열 두 개 이상(예: 상호명+집행목적)에 걸쳐 있으면, 두 열 가운데에 가장 가까운 띄어쓰기에서 나눈다."""
    cols = sorted((x, c) for c, x in anchors.items() if c in TEXT_COLS and b["x"] < x < b["x"] + b["w"])
    text = b["text"]
    if len(cols) < 2 or " " not in text:
        return [b]
    cut_x = (cols[0][0] + cols[1][0]) / 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    i = min(spaces, key=lambda i: abs(b["x"] + b["w"] * i / len(text) - cut_x))
    return [p for p in (_piece(b, 0, i), _piece(b, i + 1, len(text))) if p["text"]]


def group_rows(boxes):
    rows, cur, cur_y = [], [], None
    hs = sorted(b["h"] for b in boxes) or [0.01]
    tol = hs[len(hs) // 2] * 0.6
    for b in sorted(boxes, key=lambda b: b["y"] + b["h"] / 2):
        yc = b["y"] + b["h"] / 2
        if cur and abs(yc - cur_y) > tol:
            rows.append(cur)
            cur = []
        cur.append(b)
        cur_y = sum(o["y"] + o["h"] / 2 for o in cur) / len(cur)
    if cur:
        rows.append(cur)
    return rows


def nearest(anchors, x, cols):
    cands = [(abs(anchors[c] - x), c) for c in cols if c in anchors]
    return min(cands)[1] if cands else None


def to_amount(t):
    s = re.sub(r"[,원\s]", "", t)
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def parse_date(text, period_year, period_month=None):
    t = text.replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(\d{2})", t)
    if m and period_month and int(m.group(1)) == period_month:  # '719' → 7월 19일 (월별 공개 파일에서만)
        try:
            return date(period_year, period_month, int(m.group(2))).isoformat(), False
        except ValueError:
            return None, False
    m = DATE_FULL.search(t)
    try:
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat(), True
        m = DATE_SHORT.search(t)
        if m:
            return date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat(), True
        m = DATE_MD.search(t)
        if m and period_year:
            return date(period_year, int(m.group(1)), int(m.group(2))).isoformat(), False
    except ValueError:
        return None, False
    return None, False


def attendee_pass(img, anchors, top, rows_y, bottom):
    """대상 인원 열만 잘라 키워서 다시 OCR → {행 y중심: 인원}."""
    if "attendees" not in anchors:
        return {}
    xs = sorted(anchors.values())
    x = anchors["attendees"]
    left = max([v for v in xs if v < x - 1e-4], default=x - 0.04)
    right = min([v for v in xs if v > x + 1e-4], default=x + 0.04)
    x0, x1 = (left + x) / 2, (x + right) / 2
    W, H = img.size
    crop = img.crop((int(x0 * W), int(top * H), int(x1 * W), int(bottom * H)))
    crop = crop.resize((crop.width * 2, crop.height * 2))
    found = {}
    for b in ocr_image(crop):
        t = b["text"].replace("명", "").strip()
        if not re.fullmatch(r"\d{1,3}", t) or int(t) == 0:
            continue
        yc = top + (b["y"] + b["h"] / 2) * (bottom - top)
        ry = min(rows_y, key=lambda r: abs(r - yc)) if rows_y else None
        if ry is not None and abs(ry - yc) < 0.012:
            found[ry] = int(t)
    return found


def parse_pdf(path, period, known_roles=frozenset(), stats=None):
    period_year = int(period[:4]) if period and period[:4].isdigit() else None
    period_month = int(period[5:7]) if period and re.fullmatch(r"\d{4}-\d{2}", period) else None
    stats = stats if stats is not None else {}
    stats.setdefault("unreadable_date_rows", 0)
    stats.setdefault("inherited_date_rows", 0)
    doc = ocr_pdf(path)
    pdf = pdfium.PdfDocument(str(path))
    out, printed_total, anchors, header_y = [], None, {}, None
    for pi, page in enumerate(doc["pages"]):
        boxes = page["boxes"]
        a, hy = header_anchors(boxes)
        if a:
            anchors, header_y = a, hy
        elif not anchors:
            continue
        else:
            header_y = 0.0
        page_totals = []
        for b in boxes:
            if re.search(r"합\s*계|총\s*계|총\s*사용\s*금액|사용\s*금액\s*합계|^계$", b["text"].strip()):
                yc0 = b["y"] + b["h"] / 2
                same = [to_amount(p["text"]) for o in boxes if abs(o["y"] + o["h"] / 2 - yc0) < max(o["h"], b["h"]) and o["x"] > b["x"]
                        for p in split_box(o) if to_amount(p["text"]) is not None and AMOUNT.match(p["text"].replace(" ", ""))]
                if same:
                    page_totals.append(max(same))
        if page_totals:
            printed_total = (printed_total or 0) + max(page_totals)
        body = [q for b in boxes if b["y"] > header_y - 0.002 for p in split_box(b) for q in split_across_columns(p, anchors)]
        # 페이지 제목(예: '2023. 3월 의회운영업무추진비 집행내역(의장)')의 직책 — 사용자 열이 없는 서식에서 쓴다
        heads = [b for b in boxes if b["y"] < (header_y or 0.2) - 0.01 and b["w"] > 0.2]
        page_role = role_from_title(" ".join(b["text"] for b in heads)) if heads else None
        rows = group_rows(body)
        img = None
        parsed_rows = []
        for r in rows:
            cells = {k: [] for k in HEADER}
            confs = []
            for b in sorted(r, key=lambda b: b["x"]):
                t = clean_text(b["text"]) or ""
                xc = b["x"] + b["w"] / 2
                confs.append(b["conf"])
                if DATE_FULL.search(t.replace(" ", "")) or ((DATE_SHORT.search(t) or DATE_MD.search(t)) and nearest(anchors, xc, ["date", "time", "amount", "merchant_name"]) == "date"):
                    cells["date"].append(t)
                elif TIME.match(t.replace(" ", "")):
                    cells["time"].append(t)
                elif re.fullmatch(r"\d{3,4}", t) and nearest(anchors, xc, ["date", "time", "amount", "row_no", "attendees"]) == "date":
                    cells["date"].append(t)  # '719'처럼 구분자가 빠진 날짜
                elif AMOUNT.match(t.replace(" ", "")) and nearest(anchors, xc, ["amount", "attendees", "row_no", "date"]) == "amount":
                    cells["amount"].append(t)
                elif PAYMENT.match(t.replace(" ", "")):
                    cells["payment_method"].append(t)
                elif re.fullmatch(r"\d{1,3}\s*명", t):
                    cells["attendees"].append(t)
                elif re.fullmatch(r"\d{1,3}(명)?", t.replace(" ", "")):
                    col = nearest(anchors, xc, ["row_no", "attendees", "date"])
                    cells[col or "row_no"].append(t)
                else:
                    col = nearest(anchors, xc, list(anchors))
                    if col in ("date", "time", "amount", "payment_method", "row_no", "attendees"):
                        col = nearest(anchors, xc, TEXT_COLS) or col
                    if SIDO.match(t) and "merchant_address" in anchors:
                        col = "merchant_address"
                    cells[col].append(t)
            joined = " ".join(cells["merchant_name"] + cells["purpose"] + cells["user_role"])
            if re.search(r"합\s*계|총\s*계|^계$", joined) or any(re.fullmatch(r"(합\s*계|총\s*계|계)", c) for v in cells.values() for c in v):
                continue
            yc = sum(b["y"] + b["h"] / 2 for b in r) / len(r)
            parsed_rows.append((yc, cells, min(confs) if confs else 0))
        # 대상 인원 재인식
        rows_y = [yc for yc, cells, _ in parsed_rows if cells["amount"]]
        if rows_y and "attendees" in anchors:
            img = pdf[pi].render(scale=doc["dpi"] / 72).to_pil()
            extra = attendee_pass(img, anchors, max(header_y, 0.0), rows_y, min(1.0, max(rows_y) + 0.02))
        else:
            extra = {}
        if img is not None and "attendees" in anchors:
            xs = sorted(anchors.values())
            x = anchors["attendees"]
            x0 = (max([v for v in xs if v < x - 1e-4], default=x - 0.04) + x) / 2
            x1 = (x + min([v for v in xs if v > x + 1e-4], default=x + 0.04)) / 2
            hs = sorted(b["h"] for b in boxes) or [0.01]
            rh = hs[len(hs) // 2]
            W, H = img.size
            for yc, cells, _ in parsed_rows:
                if yc in extra or not cells["amount"] or cells["attendees"]:
                    continue
                cell = img.crop((int(x0 * W), int((yc - rh) * H), int(x1 * W), int((yc + rh) * H)))
                cell = cell.resize((cell.width * 3, cell.height * 3))
                for b in ocr_image(cell):
                    t = b["text"].replace("명", "").strip()
                    if re.fullmatch(r"\d{1,3}", t) and int(t) > 0:
                        extra[yc] = int(t)
                        break
        prev = None
        for yc, cells, conf in parsed_rows:
            d, full = parse_date(" ".join(cells["date"]), period_year, period_month)
            amt = next((to_amount(x) for x in reversed(cells["amount"]) if to_amount(x) is not None), None)
            inherited = False
            if d is None and amt is not None and prev is not None and (cells["time"] or cells["merchant_name"]):
                if not cells["date"]:  # 날짜 칸이 비어 있음 = 같은 날짜를 병합 셀로 한 번만 적은 표
                    d, full, inherited = prev["date"], False, True
                    stats["inherited_date_rows"] += 1
                else:
                    stats["unreadable_date_rows"] += 1
            if d is None or amt is None:
                # 날짜·금액이 없는 줄은 앞 행 칸이 줄바꿈된 것으로 본다
                if prev is not None and not cells["amount"]:
                    for k in ("merchant_name", "merchant_address", "purpose"):
                        if cells[k]:
                            prev[k] = ((prev.get(k) or "") + " " + " ".join(cells[k])).strip()
                continue
            tm = next((TIME.match(x.replace(" ", "")) for x in cells["time"] if TIME.match(x.replace(" ", ""))), None)
            # 페이지 전체 OCR에서 읽은 값이 우선, 없을 때만 열을 잘라 다시 읽은 값(0명은 테두리·옆 칸 숫자 오독이라 버림)
            nums = [int(re.sub(r"\D", "", x)) for x in cells["attendees"] if re.sub(r"\D", "", x)]
            att = next((n for n in nums if n > 0), None) or (extra.get(yc) or None)
            row = {
                "date": d, "time": f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm and int(tm.group(1)) < 24 else None,
                "amount": amt, "merchant_name": clean_text(" ".join(cells["merchant_name"])),
                "merchant_address": clean_text(" ".join(cells["merchant_address"])), "purpose": clean_text(" ".join(cells["purpose"])),
                "user_role": sanitize_role(" ".join(cells["user_role"]), known_roles) or page_role,
                "department": sanitize_role(" ".join(cells["department"]), known_roles),
                "budget_item": clean_text(" ".join(cells["budget_item"])), "attendees": att or None,
                "payment_method": clean_text(" ".join(cells["payment_method"])),
                "parse_confidence": "MEDIUM" if (full and conf >= 0.5 and not inherited) else "LOW",
                "ocr_min_conf": conf,
            }
            out.append(row)
            prev = row
    return out, printed_total


def sanitize_role(text, known_roles=frozenset()):
    """OCR 칸에서 직책만 고른다. 이 의회의 텍스트 자료에 실제로 나오는 직책명과 같을 때만 쓰고,
    아니면(예: '김OO위원장'처럼 성명이 붙은 경우) 버린다 — 성명을 직책으로 저장하지 않기 위해서다."""
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return None
    for tok in [compact] + re.split(r"[\s,·/()]+", text or ""):
        tok = tok.strip()
        if tok in known_roles:
            return tok
    m = ROLE_PATTERN.fullmatch(compact)
    if m and (not known_roles or compact in known_roles or compact in ("의장", "부의장", "제1부의장", "제2부의장")):
        return compact
    return None


def role_from_title(title):
    t = re.sub(r"\s+", "", title or "")
    m = re.search(r"([가-힣]+위원장)", t)
    if m:
        return m.group(1)
    for role in ("부의장", "의장", "교섭단체", "사무국"):
        if role in t:
            return {"사무국": "의회사무국"}.get(role, role)
    m = re.search(r"([가-힣]+위원회)", t)
    return m.group(1) if m else None


def budget_from_title(title):
    t = re.sub(r"\s+", "", title or "")
    if "공통경비" in t:
        return "의정운영공통경비"
    if "의회운영" in t or "의장" in t or "위원장" in t or "교섭단체" in t:
        return "의회운영업무추진비"
    if "시책" in t:
        return "시책추진업무추진비"
    if "기관운영" in t:
        return "기관운영업무추진비"
    return None


def main():
    only = set(sys.argv[1:])
    for rp in sorted(STAGING.glob("*_parse_report.json")):
        slug = rp.name.replace("_parse_report.json", "")
        if only and slug not in only:
            continue
        rep = json.loads(rp.read_text())
        files = rep if isinstance(rep, list) else rep.get("files", [])
        # 수집 범위(2022-07, 제9대) 밖의 과거 스캔본은 OCR 대상에서 뺀다
        todo = [f for f in files if f.get("status") == "unparsed" and OCR_REASON.search(f.get("reason") or "")
                and (f.get("period") or "9999") >= "2022"]
        if not todo:
            continue
        manifest = json.loads((RAW / slug / "manifest.json").read_text())
        known = set()
        main_staging = STAGING / f"{slug}.jsonl"
        if main_staging.exists():
            for line in main_staging.open(encoding="utf-8"):
                r = json.loads(line)
                if r.get("user_role"):
                    known.add(re.sub(r"\s+", "", r["user_role"]))
        known = frozenset(known)
        reg = json.loads((STAGING / "councils" / f"{slug}.json").read_text()) if (STAGING / "councils" / f"{slug}.json").exists() else {}
        council = reg.get("name") or {"seoul": "서울특별시의회", "gwanak": "관악구의회", "mapo": "마포구의회"}.get(slug, slug)
        rows, report = [], []
        for f in todo:
            fname = f.get("file") or f.get("filename")
            post = next((p for p in manifest if p["post_title"] == f.get("post_title") and any(a["filename"] == fname for a in p["attachments"])),
                        None) or next((p for p in manifest if any(a["filename"] == fname for a in p["attachments"])), None)
            if not post:
                report.append({"file": fname, "status": "unparsed", "reason": "원본 목록에서 파일을 찾지 못함"})
                continue
            att = next(a for a in post["attachments"] if a["filename"] == fname)
            path = ROOT / att["local_path"]
            if path.suffix.lower() != ".pdf":
                report.append({"file": fname, "status": "unparsed", "reason": "PDF가 아님"})
                continue
            period = f.get("period") or post.get("period")
            stats = {}
            try:
                parsed, printed = parse_pdf(path, period, known, stats)
            except Exception as e:  # 손상 파일 등
                report.append({"file": fname, "period": period, "status": "unparsed", "reason": f"OCR 오류: {e}"})
                continue
            total = sum(r["amount"] for r in parsed)
            check = None if printed is None else ("일치" if printed == total else f"불일치(인쇄 {printed:,} / 읽음 {total:,})")
            role_t, budget_t = role_from_title(f"{post['post_title']} {fname}"), budget_from_title(f"{post['post_title']} {fname}")
            for i, r in enumerate(parsed):
                rows.append({
                    "source_id": slug, "council": council, "doc_id": f"{slug}:{att['sha256'][:12]}", "doc_title": fname,
                    "doc_url": att["url"], "post_url": post["post_url"], "period": period, "row_no": i + 1,
                    "budget_item": r["budget_item"] or budget_t, "budget_item_inferred": not r["budget_item"],
                    "department": r["department"], "user_role": r["user_role"] or role_t, "date": r["date"], "time": r["time"],
                    "amount": r["amount"], "merchant_name": r["merchant_name"], "merchant_address": r["merchant_address"],
                    "purpose": r["purpose"], "attendees": r["attendees"], "payment_method": r["payment_method"],
                    "parse_confidence": "MEDIUM" if (r["parse_confidence"] == "MEDIUM" and check == "일치") else "LOW",
                    "ocr": True, "ocr_min_conf": r["ocr_min_conf"],
                })
            report.append({"file": fname, "period": period, "status": "parsed" if parsed else "unparsed", "rows": len(parsed), **stats,
                           "amount_sum": total, "printed_total": printed, "total_check": check,
                           "reason": None if parsed else "OCR 결과에서 표를 찾지 못함"})
            print(f"{slug} {fname[:50]}: {len(parsed)} rows, {check}", file=sys.stderr)
        write_jsonl(STAGING / f"{slug}_ocr.jsonl", rows)
        (STAGING / f"{slug}_ocr_report.json").write_text(json.dumps({"engine": "apple-vision", "files": report}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
