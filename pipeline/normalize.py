"""KA-money 회계보고와 지방의회 집행 내역을 공통 형식으로 정규화한다.

국회의원 정치자금은 data/raw/ka-money/의 수입·지출 엑셀에서 읽는다.
지방의회 경비는 등록된 의회별 data/staging/<slug>.jsonl과 OCR 추출 행을 읽는다.
결과는 data/normalized/에 저장한다.
  expenditures.jsonl   재원·회계 유형을 구분한 개별 지출
  subjects.json        지출 주체(의원·의회 직책·위원회·사무국 등)
  merchants.json       사업자번호, 상호와 지역, 상호 순으로 식별한 거래처
  documents.json       지출의 doc_id로 찾을 수 있는 원본 문서 정보
  funding_types.json   재원·회계 유형
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import openpyxl

from ka_catalog import workbook
from councils import load_registry
from ocr_overlay import load_rows as load_ocr_rows

from common import (NORMALIZED, RAW, ROOT, STAGING, address_region, council_category, mask_contacts, period_range, split_name_address, clean_text, day_info, display_bizno,
                    merchant_key, merchant_kind, parse_bizno, read_jsonl, short_hash, write_json, write_jsonl)

FUNDING_TYPES = {
    "POLITICAL_FUND": {
        "label": "정치자금 (국회의원)",
        "description": "국회의원 정치자금 회계에서 지출된 금액. 후원회 기부금·본인 자산 등 세금 이외 재원이 포함되며, 선거비용은 제외된 자료입니다.",
        "basis": "정치자금법 / 중앙선관위 정치자금 수입·지출보고서",
    },
    "COUNCIL_OPERATION": {
        "label": "의회운영업무추진비",
        "description": "의장·부의장·상임위원장 등 직책 수행을 위해 편성된 지방의회 예산(세금).",
        "basis": "지방자치단체 업무추진비 집행에 관한 규칙",
    },
    "COUNCIL_COMMON": {
        "label": "의정운영공통경비",
        "description": "위원회 활동·의회 행사 등 의정 운영에 공통으로 쓰는 경비. 특정 의원 개인 지출이 아닙니다.",
        "basis": "지방자치단체 예산편성 운영기준",
    },
    "INSTITUTION_OPERATION": {
        "label": "기관운영업무추진비",
        "description": "의회사무국(공무원)의 기관 운영 경비. 의원 지출이 아닙니다.",
        "basis": "지방자치단체 업무추진비 집행에 관한 규칙",
    },
    "POLICY_PROMOTION": {
        "label": "시책추진업무추진비",
        "description": "의회사무국의 시책 추진 경비. 의원 지출이 아닙니다.",
        "basis": "지방자치단체 업무추진비 집행에 관한 규칙",
    },
    "DEPARTMENT_OPERATION": {
        "label": "부서운영업무추진비",
        "description": "의회사무국 부서 운영 경비. 의원 지출이 아닙니다.",
        "basis": "지방자치단체 업무추진비 집행에 관한 규칙",
    },
    "NEGOTIATION_GROUP": {
        "label": "교섭단체 업무추진비",
        "description": "교섭단체(정당) 대표의원 등의 의회 운영 경비.",
        "basis": "지방자치단체 업무추진비 집행에 관한 규칙",
    },
    "OTHER_COUNCIL": {
        "label": "기타 의회 경비",
        "description": "비목을 확인할 수 없는 지방의회 경비.",
        "basis": None,
    },
}

ACCOUNT_PREFIX = {"후": "후원회기부금", "자": "자산", "보": "보조금", "정": "정당지원금"}
PAYMENT_RE = re.compile(r"(체크카드|신용카드|카드|계좌입금|계좌이체|자동이체|이체|현금|기타)")
INDIVIDUAL_CATEGORIES = ("인건비_",)

# 지방의회는 전·후반기에 직책 보유자가 바뀔 수 있어 대수와 전·후반기를 함께 구분한다.
# 2018년 7월에 개원한 구의회는 제8대, 서울특별시의회는 제10대다(councils.py의 term_base_2018).


def council_term(d, source_id):
    start_year = 2018 + 4 * ((d.year - (1 if d.month < 7 else 0) - 2018) // 4)
    n = COUNCIL_SOURCES[source_id]["term_base_2018"] + (start_year - 2018) // 4
    first_half = date(start_year, 7, 1) <= d <= date(start_year + 2, 6, 30)
    s, e = (date(start_year, 7, 1), date(start_year + 2, 6, 30)) if first_half else (date(start_year + 2, 7, 1), date(start_year + 4, 6, 30))
    return f"제{n}대 {'전반기' if first_half else '후반기'}", s.isoformat(), e.isoformat()



def funding_type_of(budget_item):
    b = budget_item or ""
    if "공통경비" in b:
        return "COUNCIL_COMMON"
    if "교섭단체" in b:
        return "NEGOTIATION_GROUP"
    if "의회운영" in b:
        return "COUNCIL_OPERATION"
    if "기관운영" in b:
        return "INSTITUTION_OPERATION"
    if "시책" in b:
        return "POLICY_PROMOTION"
    if "부서운" in b or "정원가산" in b:
        return "DEPARTMENT_OPERATION"
    return "OTHER_COUNCIL"


def normalize_role(role, funding):
    k = re.sub(r"\s+", "", clean_text(role) or "")
    if not k:
        return {"COUNCIL_COMMON": "의정운영공통경비(사용자 미기재)"}.get(funding, "사무국(사용자 미기재)")
    if "교섭단체" in k:
        if "국민의힘" in k or "국힘" in k:
            return "교섭단체 국민의힘"
        if "민주" in k:
            return "교섭단체 더불어민주당"
        return "교섭단체"
    k = re.sub(r"국힘", "국민의힘", k)
    k = re.sub(r"(?<!더불어)민주당", "더불어민주당", k)
    return {"의회사무국장": "사무국장", "운영위원장": "의회운영위원장", "예산결산위원장": "예산결산특별위원장",
            "교섭단체대표": "교섭단체"}.get(k, k)


def role_type(role, funding):
    r = role or ""
    # 직책명이 분명하면 재원과 관계없이 직책으로 본다 (예: 의장 비서실의 기관운영업무추진비)
    if re.fullmatch(r"(제\d)?부?의장", r) or (r.endswith("위원장") and "위원회" not in r) or r.endswith(("원내대표", "대표의원")):
        return "COUNCIL_ROLE"
    if funding in ("INSTITUTION_OPERATION", "POLICY_PROMOTION", "DEPARTMENT_OPERATION") or \
            re.search(r"사무국|사무처|전문위원|과장|팀장|국장|주무관|담당관|사무관", r) or (re.search(r"(실|과)$", r) and "위원" not in r):
        return "SECRETARIAT"
    if funding == "NEGOTIATION_GROUP" or "교섭단체" in r:
        return "NEGOTIATION_GROUP"
    if re.fullmatch(r"[가-힣]{2,4}의원", r) and not r.endswith(("구의원", "시의원")):
        return "COUNCIL_MEMBER"
    return "COUNCIL_BODY"


ATTRIBUTION_NOTE = {
    "LEGISLATOR": "의원 본인 명의 정치자금 회계에서 회계책임자가 보고한 지출입니다. 실제 결제·사용자가 의원 본인인지 보좌진인지는 자료로 구분할 수 없습니다.",
    "COUNCIL_ROLE": "해당 직책에 편성된 업무추진비입니다. 공개자료에는 사용자의 성명이 없고 직책만 있으며, 직책 보유자는 전·후반기마다 바뀔 수 있습니다.",
    "COUNCIL_BODY": "위원회·의회 공동 경비입니다. 소속 의원 개인의 지출로 귀속하지 않습니다.",
    "COUNCIL_MEMBER": "공개자료의 '사용자' 칸에 의원 성명이 직접 기재된 경비입니다. 공동경비를 해당 의원이 집행한 기록이며, 개인 용도 지출이라는 뜻은 아닙니다.",
    "NEGOTIATION_GROUP": "교섭단체(정당) 단위 경비입니다. 특정 의원 개인의 지출로 귀속하지 않습니다.",
    "SECRETARIAT": "의회사무국(공무원) 업무추진비입니다. 의원의 지출이 아닙니다.",
}


# ---------------------------------------------------------------- KA-money
# 연도마다 열 이름이 조금씩 달라(지출금회/지출, 성명-법인단체명/성명, 2023년의 계정명·과목명 추가) 이름으로 찾는다
KA_COLUMNS = {
    "seq": ("총연번", "연번"), "oid": ("의원번호",), "name": ("의원명",), "party": ("당",), "district": ("지역명",),
    "account": ("계정명",), "subject_kind": ("과목명",), "date": ("연월일",), "desc": ("내역", "내 역"),
    "inc": ("수입금회", "수입"), "exp": ("지출금회", "지출", "지출액"), "payee": ("성명-법인단체명", "성명법인단체명", "성명", "사용처"),
    "bizno": ("생년월일-사업자번호", "사업자번호"), "addr": ("주소-사무소소재지", "주소"), "biztype": ("직업-업종", "업종"),
    "receipt": ("영수증일련번호", "영수증"), "cat": ("분류",),
}


def account_label(raw):
    a = re.sub(r"\s+", "", str(raw or ""))
    if not a:
        return None
    if "자산" in a:
        return "자산"
    if "후원" in a:
        return "후원회기부금"
    if "보조금" in a:
        return "보조금"
    if "지원금" in a:
        return "정당지원금"
    return a


def expense_categories(meta, manifest):
    source = manifest.get(meta.get("expense_src"))
    categories = defaultdict(set)
    if source:
        wb = openpyxl.load_workbook(ROOT / source["local_path"], read_only=True, data_only=True)
        it = wb.worksheets[0].iter_rows(values_only=True)
        header = next(it)
        for values in it:
            row = dict(zip(header, values))
            key = (row.get("의원번호"), row.get("연월일"), to_int(row.get("지출액")), clean_text(row.get("사용처")))
            categories[key].add(row.get("분류"))
        wb.close()
    return categories


def load_ka():
    manifest = {m["filename"]: m for m in json.loads((RAW / "ka-money" / "manifest.json").read_text())}
    rows, subjects, documents = [], {}, []
    in_2023 = set()
    reports = [r for name in manifest if (r := workbook(name)) and r["detailed"]]
    for meta in sorted(reports, key=lambda r: r["id"]):
        term = meta["key"]
        if meta["src_name"] not in manifest:
            print(f"  (skip KA-money {meta['src_name']}: not downloaded)", file=sys.stderr)
            continue
        m = manifest[meta["src_name"]]
        expense_cats = expense_categories(meta, manifest)
        doc_id = meta["id"]
        documents.append({
            "doc_id": doc_id, "source_id": "ka-money", "assembly": meta["assembly"],
            "title": f"국회의원 정치자금 수입·지출 ({meta['year']}, {meta['assembly']} 회계보고분)",
            "url": m["github_url"], "sha256": m["sha256"], "fetched_at": m["fetched_at"],
            "format": "XLSX (OCR 정제본)", "period": f"{meta['period'][0]} ~ {meta['period'][1]}",
            "publisher": "오마이뉴스·경향신문·뉴스타파 (원자료: 중앙선관위 정치자금 수입·지출보고서, 정보공개청구)",
            "origin_note": "원본 PDF는 오마이뉴스 국회의원 정치자금 공개 페이지(https://omn.kr/187rv) 또는 뉴스타파 데이터포털에서 의원명으로 검색해 확인할 수 있습니다.",
        })
        if meta.get("expense_src") in manifest:
            source = manifest[meta["expense_src"]]
            documents[-1]["related_sources"] = [{k: source[k] for k in ("github_url", "sha256", "filename")}]
            documents[-1]["origin_note"] += " 지출액이 있으나 수입으로 분류된 환급은 별도 지출 공개본의 의원번호·날짜·금액·사용처가 모두 같은 행으로 분류를 확인합니다."
        wb = openpyxl.load_workbook(ROOT / m["local_path"], read_only=True, data_only=True)
        it = wb.worksheets[0].iter_rows(values_only=True)
        header = [re.sub(r"\s+", " ", str(h or "")).strip() for h in next(it)]
        col = {}
        for key, names in KA_COLUMNS.items():
            for n in names:
                if n in header:
                    col[key] = header.index(n)
                    break
        missing = {"seq", "oid", "name", "date", "exp", "inc", "payee", "cat"} - col.keys()
        if missing:
            raise ValueError(f"KA-money {meta['src_name']}: missing columns {sorted(missing)}")
        g = lambda r, k: r[col[k]] if k in col and col[k] < len(r) else None
        for r in it:
            oid = g(r, "oid")
            if oid is None:
                continue
            sid = f"na-{int(oid)}"
            s = subjects.setdefault(sid, {
                "id": sid, "type": "LEGISLATOR", "name": clean_text(g(r, "name")), "official_no": int(oid),
                "org": "국회", "terms": {}, "funding_types": ["POLITICAL_FUND"],
            })
            info = {"party": clean_text(g(r, "party")), "district": clean_text(g(r, "district"))}
            s.setdefault("report_terms", {})[doc_id] = info
            s["terms"][meta["assembly"]] = info
            if term == "23":
                in_2023.add(sid)
            cat, exp, inc = g(r, "cat"), g(r, "exp"), g(r, "inc")
            # 2025 상세본의 음수 지출 5건은 수입으로 분류되어 별도 지출본과 대조한다.
            if cat == "수입" and to_int(exp) is not None and to_int(exp) < 0 and to_int(inc) is None:
                candidates = expense_cats.get((oid, g(r, "date"), to_int(exp), clean_text(g(r, "payee"))), set())
                if len(candidates) != 1 or not next(iter(candidates)) or "수입" in candidates:
                    raise ValueError(f"KA-money refund classification requires source verification: {g(r, 'seq')}")
                cat = next(iter(candidates))
            if cat == "수입" or to_int(exp) is None:
                if cat == "수입" and to_int(inc):
                    by_year = s.setdefault("income", {}).setdefault(str(meta["year"]), Counter())
                    by_year[income_type(g(r, "desc"))] += to_int(inc)
                continue
            rows.append(dict(
                term=term, seq=str(g(r, "seq")), subject_id=sid, official_name=clean_text(g(r, "name")), date=g(r, "date"),
                desc=g(r, "desc"), amount=to_int(exp), payee=g(r, "payee"), bizno=g(r, "bizno"), addr=g(r, "addr"),
                biztype=g(r, "biztype"), receipt=g(r, "receipt"), cat=cat, account=account_label(g(r, "account")),
                doc_id=doc_id, period=meta["period"],
            ))
        if meta["year"] >= 2025:
            # The companion expense-only workbook is independently published.
            expense_name = meta["src_name"].replace("_수입지출", "")
            if expense_name not in manifest:
                raise ValueError(f"{doc_id} 대조용 지출 파일 없음")
            check = openpyxl.load_workbook(ROOT / manifest[expense_name]["local_path"], read_only=True, data_only=True)
            check_rows = check.worksheets[0].values
            fields = next(check_rows)
            amount_index = fields.index("지출액")
            amounts = [to_int(row[amount_index]) for row in check_rows if row[fields.index("의원번호")] is not None]
            check.close()
            actual = [r["amount"] for r in rows if r["doc_id"] == doc_id]
            if None in amounts or len(actual) != len(amounts) or sum(actual) != sum(amounts):
                raise ValueError(f"{doc_id} 지출 파일 건수·금액 대조 실패")
        wb.close()
    # 2024년 상반기(제21대 회계) 파일에는 제22대 총선 예비후보자의 회계도 들어 있다.
    # 2023년(현직 의원만 수록) 자료가 없는 사람은 제21대 의원이 아니라 예비후보 기간 회계로 본다.
    if in_2023:
        for sid, s in subjects.items():
            if "제21대" in s["terms"] and sid not in in_2023:
                s["precandidate"] = s["terms"].pop("제21대")
    return rows, subjects, documents


def to_int(v):
    if isinstance(v, (int, float)):
        return int(v)
    s = re.sub(r"[,\s원]", "", str(v or ""))
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def income_type(desc):
    d = re.sub(r"\s+", "", str(desc or ""))
    if "보전" in d or "보존금" in d or "보존액" in d:
        return "선거비용 보전(국가)"  # 득표율에 따라 국가가 돌려주는 선거비용 — 세금 재원
    if "기탁금" in d and "반환" in d:
        return "기탁금 반환"
    if "지정권자" in d:
        return "후원회 기부금"
    if "이월" in d or "누계" in d or "잔액" in d:
        return "이월·누계(중복 가능)"
    if "이체" in d or "전도" in d or "인계" in d:
        return "계좌 간 이체(중복 가능)"
    if "후원" in d or "기부금" in d:
        return "후원회 기부금"
    if "자산" in d:
        return "본인 자산"
    if "보조금" in d or "지원금" in d:
        return "정당 지원금·보조금"
    if "이자" in d:
        return "예금이자"
    if "이월" in d or "누계" in d:
        return "이월·누계(중복 가능)"
    if "차입" in d:
        return "차입금"
    return "기타"


def normalize_ka(rows):
    out = []
    for r in rows:
        d = r["date"].date() if isinstance(r["date"], datetime) else None
        flags = []
        if d is None:
            flags.append("DATE_UNPARSEABLE")
        elif not (r["period"][0] <= d.isoformat() <= r["period"][1]):
            flags.append("DATE_OUTSIDE_REPORT_PERIOD")
        payee = clean_text(r["payee"])
        bizno, bkind = parse_bizno(r["bizno"])
        individual = (
            bkind == "INDIVIDUAL"
            or (r["cat"] or "").startswith(INDIVIDUAL_CATEGORIES)
            or (payee is not None and re.fullmatch(r"[가-힣]", payee) is not None)
        )
        if payee and payee == r["official_name"]:
            payee_type, payee_display = "SELF", "의원 본인"
        elif individual:
            payee_type, payee_display = "INDIVIDUAL", "개인(비공개)"
        elif not payee or payee in ("null", "-"):
            payee_type, payee_display = "MISSING", None
            flags.append("PAYEE_MISSING")
        else:
            payee_type, payee_display = "BUSINESS", payee
        receipt = clean_text(r["receipt"]) or ""
        acct = re.match(r"^([가-힣])\s*[가-힣]*\s*-", receipt)
        pay = PAYMENT_RE.search(receipt)
        rno = re.search(r"-\s*(\d+)", receipt)
        desc = mask_contacts(clean_text(r["desc"]))
        if not desc:
            flags.append("DESCRIPTION_MISSING")
        out.append({
            "id": f"ka{r['term']}-{r['seq']}",
            "source_id": "ka-money",
            "doc_id": r["doc_id"],
            "row_ref": f"연번 {r['seq']}",
            "subject_id": r["subject_id"],
            "funding_type": "POLITICAL_FUND",
            "funding_account": r.get("account") or (ACCOUNT_PREFIX.get(acct.group(1)) if acct else None),
            "date": d.isoformat() if d else None,
            "time": None,
            "amount": r["amount"],
            "description": desc,
            "category": r["cat"],
            "category_source": "오마이뉴스 분류",
            "payee_raw": payee if payee_type == "BUSINESS" else None,
            "payee_display": payee_display,
            "payee_type": payee_type,
            "_bizno": bizno if payee_type == "BUSINESS" else None,
            "_bizno_kind": bkind if payee_type == "BUSINESS" else None,
            "_region": address_region(r["addr"]) if payee_type == "BUSINESS" else None,
            "biztype_raw": mask_contacts(clean_text(r["biztype"])) if payee_type == "BUSINESS" else None,
            "attendees": None,
            "payment_method": pay.group(1) if pay else None,
            "receipt_no": rno.group(1) if rno else None,
            "quality": {"ocr": True, "flags": flags},
        })
    return out


# ---------------------------------------------------------------- 지방의회
COUNCIL_SOURCES = load_registry()


def load_council(source_id):
    path = STAGING / f"{source_id}.jsonl"
    if not path.exists():
        print(f"  (skip {source_id}: no staging file)", file=sys.stderr)
        return [], {}, []
    meta = COUNCIL_SOURCES[source_id]
    staged = read_jsonl(path)
    ocr_path = STAGING / f"{source_id}_ocr.jsonl"
    if ocr_path.exists():  # 스캔·이미지 PDF를 OCR로 읽은 행 (parse_ocr.py)
        staged += load_ocr_rows(ocr_path)
    out, subjects, docs = [], {}, {}
    dup_seen = Counter()
    for i, r in enumerate(staged):
        d = date.fromisoformat(r["date"])
        funding = funding_type_of(r.get("budget_item"))
        role = normalize_role(r.get("user_role"), funding)
        rtype = role_type(role, funding)
        tname, ts, te = council_term(d, source_id)
        sid = f"{source_id}-{short_hash(role, rtype, tname, n=8)}"
        display = f"{meta['name']} (의회 공통)" if role in (meta["name"], meta["name"].replace("의회", ""), "의회") else f"{meta['name']} {role}"
        subjects.setdefault(sid, {
            "id": sid, "type": rtype, "name": display, "role": role, "org": meta["name"],
            "org_source": source_id, "term": tname, "term_start": ts, "term_end": te, "funding_types": [],
        })
        if funding not in subjects[sid]["funding_types"]:
            subjects[sid]["funding_types"].append(funding)
        docs.setdefault(r["doc_id"], {
            "doc_id": r["doc_id"], "source_id": source_id, "title": r["doc_title"], "url": r["doc_url"],
            "post_url": r["post_url"], "period": r["period"], "publisher": meta["name"],
            "format": "PDF" if r["doc_title"].lower().endswith(".pdf") else "XLSX",
        })
        flags = []
        if not r.get("attendees"):
            flags.append("ATTENDEES_MISSING")
        if not r.get("merchant_name"):
            flags.append("PAYEE_MISSING")
        if r.get("budget_item_inferred"):
            flags.append("BUDGET_ITEM_INFERRED")
        if r.get("ocr"):
            flags.append("OCR_EXTRACTED")
        if r.get('_ocr_correction'):
            flags.append('OCR_TEXT_CORRECTED')
        ps, pe = period_range(r["period"])
        if ps and not (ps <= r["date"] <= pe):
            flags.append("DATE_OUTSIDE_REPORT_PERIOD")
        payee, addr_in_name = split_name_address(r.get("merchant_name"))
        if addr_in_name and not r.get("merchant_address"):
            r["merchant_address"] = addr_in_name
        out.append({
            "id": f"{source_id}-{r['doc_id'].split(':')[1]}-{r.get('row_no') or 'i' + str(i)}",
            "source_id": source_id,
            "doc_id": r["doc_id"],
            "row_ref": f"연번 {r.get('row_no')}" if r.get("row_no") else f"{i + 1}번째 행",
            "subject_id": sid,
            "funding_type": funding,
            "funding_account": None,
            "date": r["date"],
            "time": r.get("time"),
            "amount": r["amount"],
            "description": mask_contacts(clean_text(r.get("purpose"))),
            "category": council_category(payee, r.get("purpose")),
            "category_source": "상호명·집행목적 기반 추정",
            "payee_raw": payee,
            "payee_display": payee,
            "payee_type": "BUSINESS" if payee else "MISSING",
            "_bizno": None,
            "_bizno_kind": None,
            "_region": address_region(r.get("merchant_address")) if r.get("merchant_address") else None,
            "_default_region": meta["region"],
            "biztype_raw": None,
            "attendees": r.get("attendees"),
            "payment_method": clean_text(r.get("payment_method")),
            "receipt_no": None,
            "budget_item": r.get("budget_item"),
            "quality": {"ocr": bool(r.get("ocr")), "parse_confidence": r.get("parse_confidence"), "flags": flags,
                        **({'ocr_correction': r['_ocr_correction']} if r.get('_ocr_correction') else {})},
            **({'_dedupe_original': [split_name_address(r['_ocr_original_text'].get('merchant_name'))[0],
                                    mask_contacts(clean_text(r['_ocr_original_text'].get('purpose')))]}
               if r.get('_ocr_original_text') else {}),
        })
    # 같은 문서 안에서 id 충돌(연번 중복) 방지
    ids = Counter(e["id"] for e in out)
    for e in out:
        if ids[e["id"]] > 1:
            dup_seen[e["id"]] += 1
            e["id"] = f"{e['id']}-{dup_seen[e['id']]}"
    return out, subjects, list(docs.values())


# ---------------------------------------------------------------- 중복 수록 정리
def mark_cross_document_duplicates(exps):
    """지방의회 거래가 다른 문서에 다시 실리면 처음 읽은 행을 가리키는 duplicate_of를 기록한다.
    OCR 문구를 정정해도 같은 거래로 식별할 수 있도록 거래처와 목적은 정정 전 값으로 비교한다.
    같은 문서 안의 반복은 실제 반복 결제일 수 있어 보존하고, 영수증 번호를 쓰는 정치자금은 이 비교에서 제외한다."""
    seen = {}
    n = 0
    for e in exps:
        if e["source_id"] == "ka-money" or not e["date"]:
            continue
        payee, purpose = e.get('_dedupe_original', [e.get('payee_raw'), e.get('description')])
        key = (e["subject_id"], e["date"], e.get("time"), e["amount"], payee, purpose)
        first = seen.get(key)
        if first is None:
            seen[key] = e
        elif first["doc_id"] != e["doc_id"]:
            e["duplicate_of"] = first["id"]
            e["quality"]["flags"].append("DUPLICATE_ACROSS_DOCUMENTS")
            n += 1
    print(f"cross-document duplicates excluded from totals: {n}", file=sys.stderr)


# ---------------------------------------------------------------- 직책 보유자 (의회 공식 홈페이지 기준)
def _day(v):
    if not v:
        return None
    return v if len(v) == 10 else v[:7] + "-01"


def attach_role_holders(subjects):
    """직책×기수 주체에 해당 기간 직책 보유자를 붙인다. 보유자가 확인되지 않는 기간은 '미확인'으로 남긴다."""
    idx = defaultdict(list)
    for path in sorted(STAGING.glob("role_holders*.json")):
        for h in json.loads(path.read_text()):
            idx[(h["source_id"], h["role"], h["term_label"])].append(h)
    if not idx:
        return 0
    linked = 0
    for s in subjects.values():
        if s["type"] not in ("COUNCIL_ROLE", "NEGOTIATION_GROUP") or not s.get("term_start"):
            continue
        entries = sorted(idx.get((s["org_source"], s["role"], s["term"]), []), key=lambda h: _day(h.get("start")) or "")
        if not entries:
            continue
        ts, te = s["term_start"], s["term_end"]
        holders = []
        for i, h in enumerate(entries):
            start = max(_day(h.get("start")) or ts, ts)
            nxt = _day(entries[i + 1].get("start")) if i + 1 < len(entries) else None
            end = (date.fromisoformat(nxt) - timedelta(days=1)).isoformat() if nxt else te
            if h.get("end"):
                end = min(end, _day(h["end"]) if len(h["end"]) == 10 else h["end"][:7] + "-28")
            holders.append({
                "name": h["name"], "period_start": start, "period_end": end, "elected": h.get("start"),
                "party": h.get("party"), "party_note": h.get("party_note"), "confidence": h["confidence"],
                "source_url": h["source_url"], "source_title": h.get("source_title"), "evidence": h.get("evidence_text"),
            })
        if holders[0]["period_start"] > ts:
            holders.insert(0, {"name": None, "period_start": ts,
                               "period_end": (date.fromisoformat(holders[0]["period_start"]) - timedelta(days=1)).isoformat(),
                               "note": "이 기간의 직책 보유자를 의회 홈페이지에서 확인하지 못했습니다(선출 전, 직무대리 등)."})
        s["holders"] = holders
        linked += 1
    return linked


# ---------------------------------------------------------------- 거래처 식별
def names_related(a, b):
    if a == b or a in b or b in a:
        return True
    bigrams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)} or {s}
    ba, bb = bigrams(a), bigrams(b)
    return len(ba & bb) / min(len(ba), len(bb)) >= 0.34


def assign_merchants(exps):
    """사업자번호 > (상호키, 지역) > 상호키 순으로 거래처를 식별한다."""
    alias_region = defaultdict(Counter)  # (key, region) -> bizno counts
    alias_key = defaultdict(Counter)     # key -> bizno counts (KA 내부에서만 사용)
    bizno_keys = defaultdict(Counter)
    for e in exps:
        k = merchant_key(e["payee_raw"])
        e["_key"] = k
        if e["_bizno"] and k:
            bizno_keys[e["_bizno"]][k] += 1
    # OCR에서 번호를 잘못 읽으면 서로 다른 업체가 하나로 묶일 수 있어, 해당 번호의 대표 상호와 names_related로 대조한다.
    for e in exps:
        if e["_bizno"] and e["_key"]:
            main_key = bizno_keys[e["_bizno"]].most_common(1)[0][0]
            if not names_related(e["_key"], main_key):
                e["_bizno"] = e["_bizno_kind"] = None
                e["quality"]["flags"].append("BIZNO_NAME_CONFLICT")
    # OCR로 한 자리만 다르게 읽힌 사업자번호: 대표 상호가 같고 숫자 1자리만 다르면 더 많이 쓰인 번호로 합친다
    bizno_keys = defaultdict(Counter)
    for e in exps:
        if e["_bizno"] and e["_key"]:
            bizno_keys[e["_bizno"]][e["_key"]] += 1
    by_main_key = defaultdict(list)
    for bz, keys in bizno_keys.items():
        by_main_key[keys.most_common(1)[0][0]].append((sum(keys.values()), bz))
    canonical = {}
    for group in by_main_key.values():
        group.sort(reverse=True)
        for i, (_, bz) in enumerate(group):
            if bz in canonical:
                continue
            canonical[bz] = bz
            for _, other in group[i + 1:]:
                if other not in canonical and sum(a != b for a, b in zip(bz, other)) == 1:
                    canonical[other] = bz
    variants = defaultdict(set)
    for e in exps:
        if e["_bizno"] and canonical.get(e["_bizno"], e["_bizno"]) != e["_bizno"]:
            variants[canonical[e["_bizno"]]].add(e["_bizno"])
            e["_bizno"] = canonical[e["_bizno"]]
    for e in exps:
        k = e["_key"]
        if e["_bizno"] and k:
            alias_key[k][e["_bizno"]] += 1
            if e["_region"]:
                alias_region[(k, e["_region"])][e["_bizno"]] += 1

    # 주소가 없는 행: 같은 공개 자료(source)에서 같은 상호가 한 시·군·구에서만 나오면 그 지역의 거래처로 본다
    # 예를 들어 서울시의회 ‘서울시청매점’은 주소가 빠진 행도 같은 거래처에 연결한다.
    src_key_regions = defaultdict(Counter)
    for e in exps:
        if e["_key"] and e["_region"]:
            src_key_regions[(e["source_id"], e["_key"])][e["_region"]] += 1

    def dominant(counter):
        if not counter:
            return None
        (b, c), total = counter.most_common(1)[0], sum(counter.values())
        return b if c / total >= 0.8 else None

    merchants = {}
    for e in exps:
        k = e["_key"]
        if e["payee_type"] != "BUSINESS" or not k:
            e["merchant_id"] = None
            continue
        region = e["_region"]
        inferred = False
        if not region and not e["_bizno"]:
            regs = src_key_regions.get((e["source_id"], k))
            if regs and len(regs) == 1:
                region, inferred = next(iter(regs)), True
        region = region or e.get("_default_region")
        method = None
        if e["_bizno"]:
            bz, method = e["_bizno"], "BIZNO"
        else:
            bz = dominant(alias_region.get((k, region))) if (e["_region"] or inferred) else None
            if bz:
                method = "NAME_REGION_TO_BIZNO"
            elif e["source_id"] == "ka-money" and len(k) >= 3:
                bz = dominant(alias_key.get(k))
                method = "NAME_TO_BIZNO" if bz else None
        if bz:
            mid = "b" + bz.replace("-", "")
        else:
            scope = region or e["source_id"]
            mid = "n" + short_hash(k, scope)
            method = "NAME_REGION" if region else "NAME"
        e["merchant_id"] = mid
        e["merchant_match"] = method
        m = merchants.setdefault(mid, {
            "id": mid, "names": Counter(), "regions": Counter(), "biztypes": Counter(), "bizno": None,
            "bizno_kind": None, "methods": Counter(), "sources": set(),
        })
        m["names"][e["payee_raw"]] += 1
        if e["_region"]:
            m["regions"][e["_region"]] += 1
        if e["biztype_raw"]:
            m["biztypes"][e["biztype_raw"]] += 1
        if e["_bizno"] and not m["bizno"]:
            m["bizno"], m["bizno_kind"] = e["_bizno"], e["_bizno_kind"]
        m["methods"][method] += 1
        m["sources"].add(e["source_id"])

    out = {}
    for mid, m in merchants.items():
        names = [n for n, _ in m["names"].most_common()]
        conf = "HIGH" if m["bizno"] else ("MEDIUM" if m["regions"] else "LOW")
        out[mid] = {
            "id": mid,
            "name": names[0],
            "aliases": names[1:20],
            "alias_count": len(names) - 1,
            "bizno": display_bizno(m["bizno"], m["bizno_kind"]),
            "bizno_kind": m["bizno_kind"],
            "region": m["regions"].most_common(1)[0][0] if m["regions"] else None,
            "biztypes": [b for b, _ in m["biztypes"].most_common(5)],
            "kind": merchant_kind(names[0]),
            "id_confidence": conf,
            "match_methods": dict(m["methods"]),
            "bizno_ocr_variants": len(variants.get(m["bizno"], ())) if m["bizno"] else 0,
            "sources": sorted(m["sources"]),
        }
    return out


def main():
    ka_rows, subjects, documents = load_ka()
    exps = normalize_ka(ka_rows)
    print(f"KA-money: {len(exps)} expenditures, {len(subjects)} legislators", file=sys.stderr)
    for src in COUNCIL_SOURCES:
        ce, cs, cd = load_council(src)
        exps += ce
        subjects.update(cs)
        documents += cd
        print(f"{src}: {len(ce)} expenditures, {len(cs)} subjects, {len(cd)} documents", file=sys.stderr)

    for e in exps:
        if e["date"]:
            e.update(day_info(date.fromisoformat(e["date"])))
        else:
            e.update(weekday=None, is_weekend=None, holiday=None)

    mark_cross_document_duplicates(exps)
    merchants = assign_merchants(exps)
    print(f"merchants: {len(merchants)}", file=sys.stderr)
    print(f"role subjects linked to holders: {attach_role_holders(subjects)}", file=sys.stderr)

    for s in subjects.values():
        s["attribution"] = s["type"] if s["type"] != "LEGISLATOR" else "LEGISLATOR"
        s["attribution_note"] = ATTRIBUTION_NOTE[s["type"]]
        if "income" in s:
            s["income"] = {y: dict(c) for y, c in s["income"].items()}

    for e in exps:
        e["payee_region"] = e.get("_region")  # 행 자체의 거래처 소재지(시·군·구). 프랜차이즈 본사 주소와 구분
        for k in [k for k in e if k.startswith("_")]:
            del e[k]
    exps.sort(key=lambda e: (e["source_id"], e["subject_id"], e["date"] or "", e.get("time") or "", e["id"]))

    write_jsonl(NORMALIZED / "expenditures.jsonl", exps)
    write_json(NORMALIZED / "subjects.json", list(subjects.values()), indent=1)
    write_json(NORMALIZED / "merchants.json", list(merchants.values()))
    write_json(NORMALIZED / "documents.json", documents, indent=1)
    write_json(NORMALIZED / "funding_types.json", FUNDING_TYPES, indent=1)
    print(f"total expenditures: {len(exps)}", file=sys.stderr)


if __name__ == "__main__":
    main()
