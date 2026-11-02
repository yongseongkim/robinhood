"""그룹 1 자치구의회 첨부(PDF·XLSX·XLS) → data/staging/<slug>.jsonl

헤더 이름으로 열을 매핑한다(parse_seoul.py의 매핑·값 해석 함수를 그대로 쓴다).
'사용자' 칸에 사람 이름만 적힌 의회가 있어(예: 구로구의회), 이름은 쓰지 않고 파일·게시글 제목의 직책으로 대신한다.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIPELINE))

from parse_seoul import (TOTAL_RE, SUB_LABELS, canon_payment, map_header, norm, parse_amount, parse_attendees,  # noqa: E402
                         parse_date, parse_time, pdf_is_image_text, raw_rows_pdf, sheets_xlsx, split_merchant,
                         split_merged_header, squash)

ROOT = PIPELINE.parent
RAW = ROOT / "data" / "raw"
STAGING = ROOT / "data" / "staging"

HEADER_ALIAS = {"승인일": "집행일자", "승인일자": "집행일자", "승인일시": "집행일시", "거래일": "집행일자", "거래일자": "집행일자",
                "결제일": "집행일자", "결제일자": "집행일자", "결제일시": "집행일시", "사용일자": "집행일자", "승인시간": "시간",
                "결제시간": "시간", "승인시각": "시간", "결제시각": "시간", "시각": "시간", "사용인원": "인원", "참석인원": "인원",
                "대상자": "집행대상", "구분": "사용자", "집행액": "집행금액", "사용액": "사용금액", "승인액": "금액", "결재방법": "결제방법",
                "결재수단": "결제방법"}
PARTY = re.compile(r"국민의힘|국힘|더불어민주당|민주당|민주|정의당|진보당|조국혁신당|개혁신당|무소속")


def alias_header(c):
    k = squash(c)
    return HEADER_ALIAS.get(k, c)


ROLE_WORDS = re.compile(r"의장|부의장|위원장|위원회|사무국|사무처|팀장|담당|교섭단체|대표|의원|국장|과장|전문위원|비서|주무관|팀|실$|과$")


def infer_budget(*texts):
    t = " ".join(x or "" for x in texts)
    if "공통경비" in t:
        return "의정운영공통경비"
    if "기관운영" in t:
        return "기관운영업무추진비"
    if "시책추진" in t:
        return "시책추진업무추진비"
    if "부서운영" in t:
        return "부서운영업무추진비"
    if "의회운영" in t or "의장단" in t or "의장" in t or "교섭단체" in t:
        return "의회운영업무추진비"
    return None


def canon_budget_g1(v):
    """'시책' → 시책추진업무추진비 등. '업무추진비'·'의회'처럼 구분이 안 되는 값은 None(제목에서 추정)."""
    k = squash(v)
    if not k or k in ("업무추진비", "의회", "업무추진"):
        return None
    for stem, full in (("공통경비", "의정운영공통경비"), ("의회운영", "의회운영업무추진비"), ("기관", "기관운영업무추진비"),
                       ("시책", "시책추진업무추진비"), ("부서운", "부서운영업무추진비"), ("정원가산", "정원가산업무추진비")):
        if stem in k:
            return full
    return norm(v)


def role_from_title(*texts):
    t = " ".join(x or "" for x in texts)
    if "공통경비" in t:
        return "의회(의정운영공통경비)"
    if "교섭단체" in t and "의장단" not in t:
        return "교섭단체"
    if "사무국" in t or "기관운영" in t or "시책추진" in t or "부서운영" in t:
        return "의회사무국"
    if "부의장" in t and "의장단" not in t:
        return "부의장"
    if "의장단" in t or "의회운영" in t:
        return "의장단"
    if "의장" in t:
        return "의장"
    return "미기재"


def amount_of(v):
    if isinstance(v, str):
        v = v.replace("₩", "").replace("\\", "").replace("￦", "")
    return parse_amount(v)


COMMITTEE_STEM = re.compile(r"^(의회운영|운영|행정|재경|재무|기획|경제|복지|보건|건설|도시|환경|교통|교육|문화|안전|예산|결산|자치|사회|산업|주민|미래|"
                            r"생활|관광|체육|재정|경제|공원|녹지|주택)+$")


def clean_role(cell, fallback):
    """사용자 칸: 직책이면 그대로, '의장 홍길동'이면 직책만, 사람 이름만이면 제목의 직책으로."""
    v = norm(cell)
    if not v:
        return fallback, False
    v = v.replace("\n", " ")
    if re.search(r"업무추진비|공통경비", v) or re.fullmatch(r"[\d.\s]+", v):
        return fallback, False
    if re.fullmatch(r"[가-힣]{2,4}의원", re.sub(r"\s+", "", v)) and not v.endswith(("구의원", "시의원")):
        return fallback, True  # 'OOO의원' → 성명 비공개
    if ROLE_WORDS.search(v):
        # '의장 홍길동', '홍길동 의원'에서 이름 부분 제거 (2~4자 한글 단어 중 직책어가 아닌 것)
        parts = [p for p in re.split(r"[\s/(),·]+", v) if p]
        keep = [p for p in parts if ROLE_WORDS.search(p) or not re.fullmatch(r"[가-힣]{2,4}", p)]
        role = " ".join(keep).strip()
        if role in ("의원", ""):
            return fallback, True
        if role == "대표의원":
            return "교섭단체 대표의원", False
        return role, role != v
    compact = re.sub(r"\s+", "", v)
    if COMMITTEE_STEM.fullmatch(compact):  # '행정재경' → 위원회 이름 (사람 이름 아님)
        return compact + ("위원회" if "공통경비" in fallback else "위원장"), False
    if re.fullmatch(r"[가-힣]{2,4}", compact) or re.fullmatch(r"[가-힣]{2,4}\(?(" + PARTY.pattern + r")\)?", compact) \
            or re.fullmatch(r"[가-힣]{2,4}\([가-힣]\)", compact):
        return fallback, True  # 사람 이름(정당 표기 포함) → 공개하지 않고 제목의 직책으로
    return v, False


def rows_to_records(rows, ctx):
    recs, rejected = [], 0
    mapping = None
    last_role = None  # 세로 병합된 '구분/사용자' 칸: 첫 행에만 값이 있다
    i = 0
    while i < len(rows):
        r = rows[i]
        i += 1
        if r and r[0] == "__SHEET__":
            mapping = None
            continue
        if r and r[0] == "__PAGE__":
            # 표에 사용자 열이 없고 페이지 제목에 직책이 있는 서식: '…집행내역(의장)'
            page_role = None
            for line in (r[1] or [])[:4]:
                pm = re.search(r"\(([^()]*(?:의장|위원장|대표|교섭단체)[^()]*)\)", line or "")
                if pm:
                    page_role = re.sub(r"\s+", "", pm.group(1))
                    break
            ctx["page_role"] = page_role
            continue
        cells = [norm(c) for c in r]
        if not any(cells):
            continue
        joined = squash("".join(c or "" for c in cells))
        looks_header = bool(re.search(r"연번|번호|일자|일시|금액", joined)) and not re.search(r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}", joined)
        if looks_header:
            nxt = rows[i] if i < len(rows) and rows[i] and rows[i][0] not in ("__PAGE__", "__SHEET__") else None
            sub = nxt if nxt and any(squash(c) in SUB_LABELS for c in nxt if c) else None
            m = map_header([alias_header(c) for c in cells], [alias_header(c) for c in sub] if sub else None)
            if not m and len([c for c in cells if c]) <= 2:
                labels = split_merged_header([c for c in cells if c])
                if labels:
                    m = map_header(labels)
            if m:
                last_role = None
                # '집행일자' 오른쪽의 이름 없는 열이 시간인 서식
                if "time" not in m and m.get("date"):
                    j = m["date"][0] + 1
                    hdr = [alias_header(c) for c in cells]
                    if j < len(hdr) and not squash(hdr[j]) and not any(j in v for v in m.values()):
                        m["time"] = [j]
                mapping = m
                if sub:
                    i += 1
                continue
        if not mapping:
            continue

        def get(field):
            for j in mapping.get(field, []):
                if j < len(cells) and cells[j]:
                    return cells[j] if not isinstance(r[j], (int, float)) else r[j]
            return None

        first = cells[0] or ""
        if TOTAL_RE.match(squash(first)) or (get("merchant_name") and TOTAL_RE.match(squash(get("merchant_name")))):
            continue
        amount = amount_of(get("amount"))
        raw_date = get("date")
        if isinstance(raw_date, str) and re.match(r"^\s*\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.?\s*$", raw_date):
            raw_date = re.sub(r"\s+", "", raw_date)  # '22. 7. 19.'
        d = parse_date(raw_date, ctx["period"])
        md = re.match(r"^\s*(\d{1,2})\s*[./-]\s*(\d{1,2})\.?\s+(\d{1,2}:\d{2})", str(raw_date or ""))  # '11.01 18:12'
        if d in (None, "INVALID") and md and ctx["period"]:
            d = parse_date(f"{md.group(1)}.{md.group(2)}", ctx["period"])
        if amount is None or d in (None, "INVALID"):
            if amount is not None and raw_date:
                rejected += 1
            continue
        t = parse_time(get("time"))
        if not t and raw_date and re.search(r"\d{1,2}:\d{2}", str(raw_date)) and not str(raw_date).endswith("00:00:00"):
            t = parse_time(str(raw_date).split()[-1])
        budget = canon_budget_g1(get("budget_item"))
        inferred = False
        if not budget:
            budget, inferred = infer_budget(ctx["doc_title"], ctx["post_title"]), True
        fallback = ctx.get("page_role") or role_from_title(ctx["doc_title"], ctx["post_title"])
        role_cell = get("user_role")
        carried = False
        if not role_cell and mapping.get("user_role") and last_role:
            role_cell, carried = last_role, True
        elif role_cell:
            last_role = role_cell
        role, had_name = clean_role(role_cell, fallback)
        had_name = had_name or carried
        if re.search(r"위\s*원\s*장$|의\s*장$|대\s*표$", role):
            role = re.sub(r"\s+", "", role)  # '복지건설위 원장' → '복지건설위원장'
        if role == "위원장":  # 범용 '위원장' → 제목의 구체적 위원장명
            tm = re.search(r"([가-힣]{2,}위원장)", (ctx["doc_title"] or "") + " " + (ctx["post_title"] or ""))
            if tm and tm.group(1) != "위원장":
                role = tm.group(1)
        merchant, addr = split_merchant(get("merchant_name"), get("merchant_address"))
        rn = get("row_no")
        recs.append({
            "source_id": ctx["slug"], "council": ctx["council"], "doc_id": ctx["doc_id"], "doc_title": ctx["doc_title"],
            "doc_url": ctx["doc_url"], "post_url": ctx["post_url"], "period": ctx["period"],
            "row_no": int(rn) if rn is not None and re.fullmatch(r"\d+", str(rn).split(".")[0]) else None,
            "budget_item": budget, "budget_item_inferred": inferred, "department": norm(get("department")),
            "user_role": role, "date": d, "time": t, "amount": amount,
            "merchant_name": merchant, "merchant_address": addr, "purpose": norm(get("purpose")),
            "attendees": parse_attendees(get("attendees")), "payment_method": canon_payment(get("payment_method")),
            "parse_confidence": "HIGH" if merchant and not had_name else "MEDIUM",
        })
    return recs, rejected


def sniff(path):
    """확장자가 아니라 파일 내용으로 형식을 판정한다 (일부 게시판은 파일명이 깨져 있음)."""
    head = path.read_bytes()[:8]
    if head.startswith(b"%PDF"):
        return ".pdf"
    if head.startswith(b"PK\x03\x04"):
        import zipfile
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        if "[Content_Types].xml" in names and any(n.startswith("xl/") for n in names):
            return ".xlsx"
        return ".hwpx" if any(n.startswith("Contents/") for n in names) else ".zip"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return ".hwp" if path.suffix.lower() == ".hwp" or "hwp" in path.name.lower() else ".xls"
    return path.suffix.lower()


def clean_filename(name):
    return re.sub(r"\s*(파일\s*)?(내려받기|다운로드|미리보기|바로보기)\s*$", "", name or "").strip()


def parse_file(path, ctx):
    ext = sniff(path)
    if ext == ".pdf":  # noqa: SIM114
        if pdf_is_image_text(path):
            return None, "한글이 이미지로 들어 있는 PDF — OCR 필요(미처리)"
        rows, chars = raw_rows_pdf(path)
        if chars < 20:
            return None, "텍스트가 없는 PDF(스캔본) — OCR 필요(미처리)"
    elif ext in (".xlsx", ".xlsm", ".xls"):
        rows = []
        if path.suffix.lower() not in (".xlsx", ".xlsm", ".xls"):  # 이름이 깨진 파일: 올바른 확장자로 임시 사본
            import shutil, tempfile
            tmp = Path(tempfile.mkdtemp()) / ("f" + ext)
            shutil.copy(path, tmp)
            path = tmp
        for name, srows in sheets_xlsx(path):
            rows.append(["__SHEET__", name])
            rows.extend(srows)
    else:
        return None, f"지원하지 않는 형식({ext}) — 수동 확인 필요"
    recs, rejected = rows_to_records(rows, ctx)
    if not ctx["period"] and recs:  # 기간을 알 수 없는 파일: 수집 범위(2022-07~) 밖 거래는 버린다
        recs = [r for r in recs if r["date"] >= "2022-07-01"]
        if not recs:
            return None, "수집 범위(2022-07 이후) 밖의 과거 자료"
    if not recs:
        text = squash(" ".join(str(c) for r in rows for c in r if isinstance(c, str)))
        if re.search(r"총0건|0건|사용실적없음|집행실적없음|집행내역없음|해당없음", text):
            return None, "집행 실적 없음(0건) — 공개 파일에 거래가 없음"
    roles = {r["user_role"] for r in recs}
    for r in recs:
        role = r["user_role"]
        bare = next((x for x in roles if x != role and role.endswith(x) and 2 <= len(role) - len(x) <= 3
                     and re.fullmatch(r"[가-힣]+", role[:len(role) - len(x)])), None)
        if bare:  # '김민석미래복지위원장' → '미래복지위원장'
            r["user_role"], r["parse_confidence"] = bare, "MEDIUM"
    if not recs:
        return None, "집행내역 표를 찾지 못함" + (f" (날짜·금액 해석 실패 {rejected}행)" if rejected else "")
    return (recs, rejected), None


def period_of_title(name):
    from g1 import period_of
    return period_of(name)


def parse_council(slug, cfg):
    mpath = RAW / slug / "manifest.json"
    if not mpath.exists():
        print(f"[{slug}] no manifest", file=sys.stderr)
        return
    manifest = json.loads(mpath.read_text())
    out, report, seen = [], [], set()
    for post in sorted(manifest, key=lambda p: (p.get("period") or "", p.get("posted_date") or "")):
        for a in post["attachments"]:
            entry = {"file": clean_filename(a["filename"]), "period": post.get("period"), "post_title": post["post_title"]}
            if a.get("skipped"):
                entry.update(status="skipped", reason=a["skipped"])
            elif not re.search(r"업무추진비|업추비|공통경비", post["post_title"] + " " + a["filename"]):
                entry.update(status="skipped", reason="업무추진비·공통경비 공개 자료가 아님(같은 게시판의 다른 자료)")
            elif a.get("error"):
                entry.update(status="unparsed", reason=f"내려받기 실패: {a['error']}")
            elif a["sha256"] in seen:
                entry.update(status="skipped", reason="같은 파일이 다른 게시글에 이미 첨부됨")
            else:
                seen.add(a["sha256"])
                period = post.get("period") or period_of_title(clean_filename(a["filename"]))
                ctx = {"slug": slug, "council": cfg["name"], "doc_id": f"{slug}:{a['sha256'][:12]}", "doc_title": clean_filename(a["filename"]),
                       "doc_url": a["url"], "post_url": post["post_url"], "period": period, "post_title": post["post_title"]}
                try:
                    res, why = parse_file(ROOT / a["local_path"], ctx)
                except Exception as e:  # 손상 파일 등
                    res, why = None, f"파싱 오류: {e}"
                if res:
                    recs, rejected = res
                    out.extend(recs)
                    entry.update(status="parsed", rows=len(recs), amount_sum=sum(x["amount"] for x in recs),
                                 rejected_rows=rejected or None)
                else:
                    entry.update(status="unparsed", reason=why)
            report.append(entry)
    with open(STAGING / f"{slug}.jsonl", "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (STAGING / f"{slug}_parse_report.json").write_text(json.dumps({"files": report}, ensure_ascii=False, indent=1))
    fmts = sorted({Path(clean_filename(a["filename"])).suffix.lower().lstrip(".") for p in manifest for a in p["attachments"] if a.get("filename")})
    st = Counter(e["status"] for e in report)
    reg = {
        "source_id": slug, "name": cfg["name"], "region": cfg["region"],
        "board_url": cfg["base"] + (cfg.get("kr", "") + "/" + cfg["board"] + ".do" if cfg.get("board") else cfg.get("list", "/kr/data/bbs?bbs_id=businesswork")),
        "term_base_2018": 8, "formats": fmts,
        # 실제 거래 일자 기준(원문 연도 오기는 제외)
        "collected_from": min((r["date"] for r in out if "2022-07-01" <= r["date"] <= "2026-12-31"), default=None),
        "collected_to": max((r["date"] for r in out if "2022-07-01" <= r["date"] <= "2026-12-31"), default=None),
        "rows": len(out), "files": dict(st),
        "fields": {k: round(sum(1 for r in out if r.get(k)) / len(out), 2) if out else 0 for k in ("time", "merchant_address", "attendees")},
        "notes": cfg.get("notes", ""),
    }
    (STAGING / "councils").mkdir(parents=True, exist_ok=True)
    (STAGING / "councils" / f"{slug}.json").write_text(json.dumps(reg, ensure_ascii=False, indent=1))
    print(f"[{slug}] rows={len(out)} files={dict(st)} fields={reg['fields']}", file=sys.stderr)
