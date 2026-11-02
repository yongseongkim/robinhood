"""국회공보 정기재산변동신고 공개목록(PDF) → data/normalized/assets.json

- PDF의 표를 그대로 읽는다(텍스트 PDF, OCR 아님). 사람마다 항목 합계 = 소계, 소계 합계 - 채무 = 총계인지 확인해 보고서에 남긴다.
- 금액 단위: 원자료 천원 → 원으로 바꿔 저장.
- 부동산 위치는 시·도, 시·군·구, 읍·면·동까지만 남긴다. 지번, 건물명, 동·호수는 저장하지 않는다.
- 전세(임차)권은 '건물' 항목에 신고되지만 소유가 아니므로 따로 표시한다.
- 국회의원(의장·부의장 포함)만 다룬다. 같은 공보에 실린 국회사무처 등 공무원은 넣지 않는다.
"""
import json
import re
import sys
from collections import Counter, defaultdict

import pdfplumber

from common import NORMALIZED, RAW, SIDO

SRC = RAW / "assets"
HEADER = re.compile(r"소속\s*(\S+)\s*직위\s*(.+?)\s*성명\s*(\S+)\s*$")
SECTION = re.compile(r"^▶\s*(.+?)\s*(?:\(소계\))?$")  # '고지거부 및 등록제외사항'에는 (소계)가 없다
MEMBER_POS = {"국회의원", "국회의장", "국회부의장"}
CATEGORY = {  # 공보의 재산 구분 → 화면에 쓰는 짧은 이름
    "부동산에 관한 규정이 준용되는 권리와 자동차·건설기계·선박 및 항공기": "자동차 등",
    "정치자금법에 따른 정치자금의 수입 및 지출을 위한 예금계좌의 예금": "정치자금 계좌",
    "고지거부 및 등록제외사항": "고지거부",
    "합명·합자 및 유한회사 출자지분": "출자지분",
    "금 및 백금": "금·백금",
    "골동품 및 예술품": "골동품·예술품",
}
SIDO_FULL = re.compile(r"^(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|세종특별자치시|경기도|강원특별자치도|강원도|충청북도|충청남도|"
                       r"전북특별자치도|전라북도|전라남도|경상북도|경상남도|제주특별자치도|전남광주통합특별시)")

SIDO_SHORT = re.compile(r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)(?:시|도)?(?=\s)")


def amount(cell):
    """'1,234' / '-1,234' / '10,370\\n(3,000)'(괄호는 실거래가격) / '-' → 천원 정수."""
    if cell is None:
        return None
    first = str(cell).strip().split("\n")[0].strip()
    if first in ("", "-"):
        return None
    m = re.fullmatch(r"(-?)\s*([\d,]+)", first)
    return int(m.group(1) + m.group(2).replace(",", "")) if m else None


def flat(cell, sep=" "):
    return sep.join(str(cell or "").split("\n")).strip()


def location(desc):
    """'경기도 용인시 처인구 포곡읍 신원리 123번지 ...' → ('경기', '용인시 처인구', '포곡읍'). 지번·건물명·동호수는 버린다."""
    s = re.sub(r"\s+", " ", desc or "").strip()
    m = SIDO_FULL.match(s) or SIDO_SHORT.match(s)
    if not m:
        return ("해외·기타", None, None) if s else (None, None, None)
    sido = SIDO.get(m.group(1), m.group(1)[:2])
    toks = s[m.end():].split()
    sgg = []
    i = 0
    while i < len(toks) and len(sgg) < 2 and re.fullmatch(r"[가-힣]+(시|군|구)", toks[i]):
        sgg.append(toks[i])
        i += 1
    emd = toks[i] if i < len(toks) and re.fullmatch(r"[가-힣\d·.]+(읍|면|동|가|로)", toks[i]) else None
    if emd and emd.endswith("로"):  # 도로명 주소는 동을 알 수 없다
        emd = None
    return sido, " ".join(sgg) or None, emd


def areas(desc):
    out = []
    for label, num in re.findall(r"(대지|건물|토지)?\s*([\d,]+\.\d+)㎡", desc or ""):
        out.append((label + " " if label else "") + num + "㎡")
    return out[:2]


def events(page):
    """한 쪽의 머리글(사람)과 표 행을 위에서 아래 순서로."""
    ev = []
    for line in page.extract_text_lines():
        m = HEADER.search(line["text"])
        if m:
            ev.append((line["top"], "person", m.groups()))
    for t in page.find_tables():
        for r, row in zip(t.rows, t.extract()):
            if row and len(row) == 8:
                ev.append((r.bbox[1], "row", row))
    ev.sort(key=lambda e: e[0])
    return ev


def parse(pdf_path):
    people, cur, cat = [], None, None
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            first_row = True
            for _, kind, data in events(page):
                if kind == "person":
                    org, pos, name = data
                    cur = {"name": name, "org": org, "position": pos.strip(), "page": pno, "cats": {}, "items": [], "total": None}
                    people.append(cur)
                    cat, first_row = None, False
                    continue
                if cur is None:
                    continue
                row = data
                head = flat(row[0])
                # 머리글 행 (표 머리, 단위, 소속·직위·성명 칸)
                if head.startswith(("본인과", "소속", "(단위")) or head == "관계" or (not head and any("증가액" in str(c or "") for c in row)):
                    continue
                m = SECTION.match(head)
                if m:
                    cat = CATEGORY.get(m.group(1).strip(), m.group(1).strip())
                    cur["cats"][cat] = [amount(c) for c in row[3:7]]
                    first_row = False
                    continue
                if re.sub(r"\s", "", head) == "총계":
                    note = flat(row[7])
                    ch = re.search(r"증감액:\s*(-?[\d,]+)", note)
                    val = re.search(r"가액변동:\s*(-?[\d,]+)", note)
                    cur["total"] = [amount(c) for c in row[3:7]] + [int(ch.group(1).replace(",", "")) if ch else None,
                                                                   int(val.group(1).replace(",", "")) if val else None]
                    first_row = False
                    continue
                amounts = [amount(c) for c in row[3:7]]
                # 쪽이 바뀌며 나뉜 행: 다음 쪽에 관계·종류·금액이 한 번 더 찍히고 명세만 이어진다
                last = cur["items"][-1] if cur["items"] else None
                if (first_row and last and last["cat"] == cat and last["relation"] == head and last["kind"] == flat(row[1], "")
                        and [last["prev"], last["inc"], last["dec"], last["cur"]] == amounts
                        and not SIDO_FULL.match(flat(row[2]))):  # 새 주소로 시작하면 금액이 같아도 다른 항목 (예: 같은 오피스텔 두 호실)
                    last["desc"] += " " + flat(row[2])
                    first_row = False
                    continue
                # 쪽이 바뀌며 이어지는 행: 관계·종류·금액 없이 명세만 있다
                if not head and not flat(row[1]) and all(a is None for a in amounts) and cur["items"]:
                    cur["items"][-1]["desc"] += " " + flat(row[2])
                    first_row = False
                    continue
                if first_row and not head and cur["items"] and cur["items"][-1]["cur"] is None:
                    it = cur["items"][-1]
                    it["desc"] += " " + flat(row[2])
                    it["prev"], it["inc"], it["dec"], it["cur"] = amounts
                    it["reason"] = it["reason"] or flat(row[7])
                    first_row = False
                    continue
                cur["items"].append({"cat": cat, "relation": head, "kind": flat(row[1], ""), "desc": flat(row[2]),
                                     "prev": amounts[0], "inc": amounts[1], "dec": amounts[2], "cur": amounts[3], "reason": flat(row[7])})
                first_row = False
    return people


def check(p):
    """항목 합계 = 소계, (소계 합계 - 채무) = 총계인지."""
    issues = []
    by_cat = defaultdict(int)
    for it in p["items"]:
        by_cat[it["cat"]] += it["cur"] or 0
    for c, sub in p["cats"].items():
        if c == "고지거부" or sub[3] is None:
            continue
        if by_cat[c] != sub[3]:
            issues.append(f"{c} 항목 합계 {by_cat[c]} ≠ 소계 {sub[3]}")
    if p["total"]:
        net = sum((v[3] or 0) * (-1 if c == "채무" else 1) for c, v in p["cats"].items() if c != "고지거부")
        if net != p["total"][3]:
            issues.append(f"소계 합계 {net} ≠ 총계 {p['total'][3]}")
    else:
        issues.append("총계 없음")
    return issues


def link(people):
    """국회의원 → 정치자금 주체(id)·정당·지역구.
    공개 시점(3월)의 제22대 의원이므로 정치자금 자료의 제22대 주체 중 이름이 한 명뿐일 때 연결한다
    (그 뒤 지방선거 등으로 의원직을 그만둔 사람도 연결된다). 주체가 없으면(승계 의원 등) 현직 명단의 정당만 붙인다."""
    subjects = json.loads((NORMALIZED / "subjects.json").read_text())
    by_name = defaultdict(list)
    for sj in subjects:
        if sj["type"] == "LEGISLATOR" and "제22대" in (sj.get("terms") or {}):
            by_name[re.sub(r"\(.*?\)$", "", sj["name"]).strip()].append(sj)
    members = json.loads((RAW / "assembly" / "members_current.json").read_text()) if (RAW / "assembly" / "members_current.json").exists() else []
    mem_by_name = defaultdict(list)
    for m in members:
        mem_by_name[m["HG_NM"]].append(m)
    for p in people:
        cands = by_name.get(p["name"], [])
        if len(cands) == 1:
            t = cands[0]["terms"]["제22대"]
            p["sid"], p["party"], p["district"] = cands[0]["id"], t.get("party"), t.get("district")
            continue
        mems = mem_by_name.get(p["name"], [])
        p["sid"] = None
        p["party"] = mems[0]["POLY_NM"] if len(mems) == 1 else None
        p["district"] = mems[0]["ORIG_NM"] if len(mems) == 1 else None


def main():
    manifest = json.loads((SRC / "manifest.json").read_text()) if (SRC / "manifest.json").exists() else []
    if not manifest:
        print("재산공개 PDF 없음 — collect_assets.py를 먼저 실행", file=sys.stderr)
        return
    issue = max(manifest, key=lambda m: m["date"])
    raw = parse(SRC / issue["file"])
    members = [p for p in raw if p["position"] in MEMBER_POS]
    link(members)
    won = lambda v: None if v is None else v * 1000
    out, problems = [], {}
    for p in members:
        probs = check(p)
        if probs:
            problems[p["name"]] = probs
        realestate = []
        for it in p["items"]:
            if it["cat"] not in ("토지", "건물"):
                continue
            sido, sgg, emd = location(it["desc"])
            realestate.append({"cat": it["cat"], "relation": it["relation"], "kind": it["kind"], "sido": sido, "sgg": sgg, "emd": emd,
                               "area": areas(it["desc"]), "lease": bool(re.search(r"전세|임차", it["kind"])),
                               "prev": won(it["prev"]), "cur": won(it["cur"]), "reason": it["reason"]})
        refused = [it["relation"] for it in p["items"] if it["cat"] == "고지거부" and "고지거부" in it["desc"]]
        crypto = [it for it in p["items"] if it["cat"] == "가상자산"]
        t = p["total"] or [None] * 6
        out.append({
            "name": p["name"], "position": p["position"], "sid": p["sid"], "party": p["party"], "district": p["district"], "page": p["page"],
            "total": {"prev": won(t[0]), "inc": won(t[1]), "dec": won(t[2]), "cur": won(t[3]), "change": won(t[4]), "valuation": won(t[5])},
            "cats": {c: {"prev": won(v[0]), "cur": won(v[3])} for c, v in p["cats"].items() if c != "고지거부"},
            "realestate": realestate, "refused": refused, "cryptoCount": len(crypto), "checked": not probs,
        })
    report = {"people": len(out), "linked": sum(1 for p in out if p["sid"]), "items": sum(len(p["items"]) for p in members),
              "realestate": sum(len(p["realestate"]) for p in out), "problems": problems,
              "unlinked": [p["name"] for p in out if not p["sid"]]}
    (NORMALIZED / "assets.json").write_text(json.dumps({
        "source": {"title": issue["title"], "notice": "국회공직자윤리위원회공고 제2026-3호" if "2026-54" in issue["title"] else None,
                   "published": issue["date"], "basis": f"{int(issue['date'][:4]) - 1}-12-31", "url": issue["url"], "sha256": issue["sha256"],
                   "listPage": issue["list_page"]},
        "people": out, "report": report}, ensure_ascii=False))
    print(json.dumps({k: (v if not isinstance(v, (dict, list)) else len(v)) for k, v in report.items()}, ensure_ascii=False), file=sys.stderr)
    for name, probs in list(problems.items())[:15]:
        print(f"  확인 필요 {name}: {probs}", file=sys.stderr)


if __name__ == "__main__":
    main()
