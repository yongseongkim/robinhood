"""열린국회정보 의정활동(인적사항·대표발의 법률안)을 정치자금 자료의 의원(KA-money 의원번호 주체)과 연결한다.

연결 기준
- 현직(제22대): 이름 + 지역구가 같으면 연결. 지역구 표기가 달라도 이름이 현직 중 유일하면 '이름' 기준으로 연결.
- 법률안·표결: 의원 코드(MONA_CD)가 연결된 현직 의원이면 그 의원. 아니면(제21대만 지낸 의원 등)
  이름이 해당 대수 정치자금 주체 중 한 명뿐이고, 그 이름으로 나온 (연결 안 된) 의원 코드도 하나뿐일 때만 연결한다.
  이미 다른 코드로 연결된 주체에는 이름으로 붙이지 않는다 (예: 2026년 보궐로 들어온 동명이인 박지원).
결과: data/normalized/assembly.json
"""
import json
import re
import sys
from collections import Counter, defaultdict

from common import NORMALIZED, RAW

RESULT_GROUP = {
    "원안가결": "가결", "수정가결": "가결", "대안반영폐기": "대안에 반영", "수정안반영폐기": "대안에 반영",
    "임기만료폐기": "임기만료 폐기", "철회": "철회", "부결": "부결·폐기", "폐기": "부결·폐기",
}


def base_name(n):
    return re.sub(r"\(.*?\)$", "", n or "").strip()


def compact(s):
    return re.sub(r"\s+", "", s or "")


def district_rest(d):
    """시·도 이름을 뺀 선거구 이름 ('전남광주통합특별시 해남군완도군진도군' == '전남 해남군완도군진도군')."""
    d = (d or "").strip()
    return compact(d.split(" ", 1)[1]) if " " in d else compact(d)


def result_group(r):
    return RESULT_GROUP.get(r or "", "심사 중" if not r else r)


def main():
    folder = RAW / "assembly"
    if not (folder / "manifest.json").exists():
        print("열린국회정보 자료 없음 — collect_assembly.py를 먼저 실행", file=sys.stderr)
        return
    members = json.loads((folder / "members_current.json").read_text())
    bills = {age: json.loads((folder / f"bills_{age}.json").read_text()) for age in ("21", "22")}
    subjects = [s for s in json.loads((NORMALIZED / "subjects.json").read_text()) if s["type"] == "LEGISLATOR"]

    # 현직 의원 ↔ 주체
    by_term = {t: [s for s in subjects if t in s.get("terms", {})] for t in ("제21대", "제22대")}
    name_count22 = Counter(base_name(s["name"]) for s in by_term["제22대"])
    member_name_count = Counter(m["HG_NM"] for m in members)
    code_to_sid, matched = {}, {}
    for m in members:
        cands = [s for s in by_term["제22대"] if base_name(s["name"]) == m["HG_NM"]]
        exact = [s for s in cands if district_rest(s["terms"]["제22대"].get("district")) == district_rest(m["ORIG_NM"])]
        if len(exact) == 1:
            sid, how = exact[0]["id"], "이름·지역구 일치"
        elif len(cands) == 1 and member_name_count[m["HG_NM"]] == 1:
            sid, how = cands[0]["id"], "이름 일치(지역구 표기 다름)"
        else:
            continue
        code_to_sid[m["MONA_CD"]] = sid
        matched[sid] = {"member": {k: m.get(k) for k in ("HG_NM", "POLY_NM", "ORIG_NM", "ELECT_GBN_NM", "CMITS", "REELE_GBN_NM",
                                                          "UNITS", "JOB_RES_NM", "HOMEPAGE")}, "match": how}

    # 이름 → 의원 코드 (대수별). 한 이름에 코드가 둘 이상이면 동명이인이 있으므로 이름으로 연결하지 않는다.
    codes_by_name = defaultdict(lambda: defaultdict(set))
    parties_by_code = defaultdict(lambda: defaultdict(set))  # 표결 기록의 정당 (동명이인 구분용)
    for age, rows in bills.items():
        for b in rows:
            if b.get("RST_PROPOSER") and b.get("RST_MONA_CD"):
                codes_by_name[age][b["RST_PROPOSER"]].add(b["RST_MONA_CD"])
    for age in ("21", "22"):
        vdir = folder / "votes" / age
        for p in (vdir.glob("*.json") if vdir.exists() else []):
            for mona, name, party, _result in json.loads(p.read_text())["votes"]:
                if name and mona:
                    codes_by_name[age][name].add(mona)
                    parties_by_code[age][mona].add(party)

    linked = set(code_to_sid.values())

    def by_name_ok(age, name, code, names, by_name):
        # 이미 코드로 연결된 주체에 다른 코드를 이름으로 붙이지 않는다 (다른 사람)
        return (names[name] == 1 and by_name[name] not in linked
                and len(codes_by_name[age][name] - set(code_to_sid)) <= 1)

    def by_party(age, name, code):
        """동명이인: 이 의원 코드의 표결 정당이 한결같고, 같은 이름·같은 정당 주체가 하나뿐이면 연결 (예: 제21대 김병욱 두 명)."""
        if len(parties_by_code[age][code]) != 1:
            return None
        term, party = f"제{age}대", next(iter(parties_by_code[age][code]))
        same = [x for x in by_term[term] if base_name(x["name"]) == name and x["terms"][term].get("party") == party]
        other = [c for c in codes_by_name[age][name] if c != code and parties_by_code[age][c] == {party}]
        return same[0]["id"] if len(same) == 1 and not other and same[0]["id"] not in linked else None

    # 법률안 ↔ 주체
    per_sid = defaultdict(lambda: defaultdict(list))
    co_count = defaultdict(Counter)
    stats = Counter()
    for age, rows in bills.items():
        term = f"제{age}대"
        names = Counter(base_name(s["name"]) for s in by_term[term])
        by_name = {base_name(s["name"]): s["id"] for s in by_term[term]}
        for b in rows:
            sid = code_to_sid.get(b.get("RST_MONA_CD"))
            if sid is None and b.get("RST_PROPOSER"):
                n = b["RST_PROPOSER"]
                if by_name_ok(age, n, b.get("RST_MONA_CD"), names, by_name):
                    sid = by_name[n]
                    stats[f"{age}_name"] += 1
                elif names[n] > 1 and (sid := by_party(age, n, b.get("RST_MONA_CD"))):
                    stats[f"{age}_party"] += 1
                elif names[n] >= 1:
                    stats[f"{age}_ambiguous"] += 1
                else:
                    stats[f"{age}_no_subject"] += 1
            elif sid:
                stats[f"{age}_code"] += 1
            if sid:
                per_sid[sid][age].append([b["BILL_NO"], b["BILL_NAME"], b.get("COMMITTEE"), b.get("PROPOSE_DT"),
                                          b.get("PROC_RESULT"), b.get("DETAIL_LINK")])
            for code in (b.get("PUBL_MONA_CD") or "").split(","):
                code = code.strip()
                if code in code_to_sid:
                    co_count[code_to_sid[code]][age] += 1

    # 본회의 표결 (collect_votes.py가 받은 만큼)
    votes = defaultdict(lambda: defaultdict(Counter))      # sid -> age -> 결과별 건수
    vote_list = defaultdict(lambda: defaultdict(list))     # sid -> age -> [(날짜, 의안명, 결과, BILL_ID)]
    vstats = Counter()
    for age in ("21", "22"):
        vdir = folder / "votes" / age
        if not vdir.exists():
            continue
        term = f"제{age}대"
        names = Counter(base_name(s["name"]) for s in by_term[term])
        by_name = {base_name(s["name"]): s["id"] for s in by_term[term]}
        for p in vdir.glob("*.json"):
            rec = json.loads(p.read_text())
            vstats[f"{age}_bills"] += 1
            for mona, name, _party, result in rec["votes"]:
                sid = code_to_sid.get(mona)
                if sid is None and name and by_name_ok(age, name, mona, names, by_name):
                    sid = by_name[name]
                elif sid is None and name and names[name] > 1:
                    sid = by_party(age, name, mona)
                if sid is None:
                    vstats[f"{age}_unmatched_votes"] += 1
                    continue
                votes[sid][age][result] += 1
                vote_list[sid][age].append(((rec.get("VOTE_DATE") or "")[:8], rec.get("BILL_NAME"), result, rec["BILL_ID"]))

    out = {}
    for sid in set(matched) | set(per_sid) | set(votes):
        entry = dict(matched.get(sid, {"member": None, "match": None}))
        entry["bills"] = {}
        for age in ("21", "22"):
            lst = sorted(per_sid[sid][age], key=lambda r: r[3] or "", reverse=True)
            if not lst and not co_count[sid][age]:
                continue
            entry["bills"][age] = {
                "lead": len(lst), "co": co_count[sid][age] if sid in matched else None,
                "results": dict(Counter(result_group(r[4]) for r in lst)), "list": lst,
            }
        if sid in votes:
            entry["votes"] = {}
            for age, cnt in votes[sid].items():
                lst = sorted(vote_list[sid][age], reverse=True)
                cast = cnt["찬성"] + cnt["반대"] + cnt["기권"]
                entry["votes"][age] = {
                    "counts": dict(cnt), "total": sum(cnt.values()), "participation": cast / sum(cnt.values()) if cnt else None,
                    # 반대·기권(소신 표결)은 모두, 나머지는 최근 20건만 — 사이트 크기 때문
                    "dissent": [[d[:4] + "-" + d[4:6] + "-" + d[6:8] if len(d) == 8 else d, n, r] for d, n, r, _ in lst if r in ("반대", "기권")],
                    "recent": [[d[:4] + "-" + d[4:6] + "-" + d[6:8] if len(d) == 8 else d, n, r] for d, n, r, _ in lst[:20]],
                }
        out[sid] = entry
    summary = {"members_current": len(members), "members_matched": len(matched), "votes": dict(vstats),
               "bills": {age: len(rows) for age, rows in bills.items()}, "attribution": dict(stats),
               "fetched_at": json.loads((folder / "manifest.json").read_text())["files"][0]["fetched_at"]}
    (NORMALIZED / "assembly.json").write_text(json.dumps({"summary": summary, "subjects": out}, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    unmatched = [m["HG_NM"] + "/" + m["ORIG_NM"] for m in members if m["MONA_CD"] not in code_to_sid]
    print(f"현직 중 연결 못 한 의원 {len(unmatched)}명: {unmatched[:15]}", file=sys.stderr)


if __name__ == "__main__":
    main()
