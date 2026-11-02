"""Normalized → site/data/*.js (정적 사이트용 데이터 조각)

API 서버 없이 동작하도록 데이터를 `RH.data(key, payload)` 형태의 JS 파일로 쓴다.
<script> 태그로 불러오므로 file:// 로 index.html을 바로 열어도 동작한다.

  site/data/meta.js              전체 목록·규칙·출처·문서 메타
  site/data/findings-index.js    탐지 결과 목록(근거 거래 id 제외)
  site/data/merchant-index.js    거래처 검색 목록
  site/data/s/<subjectId>.js     지출 주체별 거래·탐지 결과
  site/data/m/<bucket>.js        거래처별 거래 (256개 버킷)
  site/data/rank.js              순위판 (build_rank.py)
  site/data/assets.js            국회의원 재산 (build_assets.py)
"""
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from common import NORMALIZED, RAW, ROOT, SITE, STAGING, read_jsonl
from build_assets import build_assets
from build_rank import build_rank
from councils import load_registry
from rules import NOT_IMPLEMENTED, RULES

KST = timezone(timedelta(hours=9))
DATA = SITE / "data"

TX_COLS = ["id", "date", "time", "weekday", "holiday", "amount", "description", "category", "payee", "merchantId",
           "attendees", "payment", "fundingType", "account", "docId", "rowRef", "flags", "pair", "budgetItem"]
# 반복되는 문자열 열은 조각마다 사전으로 바꿔 크기를 줄인다 (app.js가 되돌림)
DICT_COLS = ["weekday", "holiday", "category", "payment", "fundingType", "account", "docId", "flags", "budgetItem"]
M_COLS = ["id", "subjectId", "date", "time", "amount", "description", "category", "fundingType", "docId", "source", "payee"]
M_DICT_COLS = ["subjectId", "category", "fundingType", "docId", "source"]


def encode(rows, cols, dict_cols):
    """열 사전 인코딩: 값 → 사전 index. 빈 값은 null, 행 끝의 null은 잘라낸다."""
    ix = {c: i for i, c in enumerate(cols)}
    dicts = {c: [] for c in dict_cols}
    lookup = {c: {} for c in dict_cols}
    out = []
    for r in rows:
        r = list(r)
        for c in dict_cols:
            v = r[ix[c]]
            if v in (None, [], ""):
                r[ix[c]] = None
                continue
            key = json.dumps(v, ensure_ascii=False)
            if key not in lookup[c]:
                lookup[c][key] = len(dicts[c])
                dicts[c].append(v)
            r[ix[c]] = lookup[c][key]
        while r and r[-1] is None:
            r.pop()
        out.append(r)
    return {"cols": cols, "dict": dicts, "rows": out}


def djb2(s):
    h = 5381
    for ch in s:
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    return h % 256


def emit(path, key, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"RH.data({json.dumps(key)},{body});\n", encoding="utf-8")
    return len(body)


def tx_row(e, pairs, rpairs):
    return [
        e["id"], e["date"], e.get("time"), e.get("weekday"), e.get("holiday"), e["amount"], e.get("description"),
        e.get("category"), e.get("payee_display"), e.get("merchant_id"), e.get("attendees"), e.get("payment_method"),
        e["funding_type"], e.get("funding_account"), e["doc_id"], e.get("row_ref"), e["quality"]["flags"],
        pairs.get(e["id"]) or rpairs.get(e["id"]), e.get("budget_item"),
    ]


def build_money(exps, subjects, subj_index, findings, registry):
    """'정치인의 돈'·'많이 쓴 곳' 화면용 집계 (재원끼리는 더하지 않는다)."""
    import numpy as np
    years = ("2023", "2024")
    people, pidx = [], {}

    def person(sid):
        if sid not in pidx:
            s = subj_index[sid]
            pidx[sid] = len(people)
            people.append([sid, s["name"], s.get("party"), s.get("district")])
        return pidx[sid]

    big_tot = {y: Counter() for y in years}
    sub_tot = {y: defaultdict(Counter) for y in years}
    sid_big = {y: defaultdict(Counter) for y in years}
    sid_total = {y: Counter() for y in years}
    for e in exps:
        if e["source_id"] != "ka-money" or not e["date"] or e["date"][:4] not in years or not e.get("category"):
            continue
        y, big = e["date"][:4], e["category"].split("_")[0]
        big_tot[y][big] += e["amount"]
        sub_tot[y][big][e["category"]] += e["amount"]
        sid_big[y][big][e["subject_id"]] += e["amount"]
        sid_total[y][e["subject_id"]] += e["amount"]
    income = {y: Counter() for y in years}
    for sj in subjects:
        for y, types in (sj.get("income") or {}).items():
            if y in income:
                income[y].update(types)
    flagged = {(f["period"]["label"][:4], f.get("category"), f["subjectId"]): f["id"] for f in findings if f["ruleId"] == "CATEGORY_SPEND_OUTLIER"}
    leg = {}
    for y in years:
        cats = []
        for big, amt in big_tot[y].most_common():
            vals = {sid: v for sid, v in sid_big[y][big].items() if v > 0 and sid in subj_index}
            arr = np.array(list(vals.values())) if vals else np.array([0])
            cats.append({
                "name": big, "amount": amt, "subs": [[k, v] for k, v in sub_tot[y][big].most_common()],
                "median": float(np.median(arr)), "p95": float(np.percentile(arr, 95)), "n": len(vals),
                "dots": [[person(sid), v, flagged.get((y, big, sid))] for sid, v in sorted(vals.items(), key=lambda kv: kv[1])],
            })
        parties = defaultdict(list)
        for sid, tot in sid_total[y].items():
            if tot > 0 and sid in subj_index:
                parties[subj_index[sid].get("party") or "미상"].append(tot)
        leg[y] = {
            "total": sum(big_tot[y].values()), "legislators": sum(1 for v in sid_total[y].values() if v > 0),
            "median": float(np.median([v for v in sid_total[y].values() if v > 0])) if sid_total[y] else 0,
            "categories": cats,
            "income": [[k, v] for k, v in income[y].most_common() if "중복 가능" not in k],
            "incomeCarry": sum(v for k, v in income[y].items() if "중복 가능" in k),
            "parties": sorted(([p, len(v), sum(v), float(np.median(v))] for p, v in parties.items()), key=lambda r: -r[1]),
        }

    # 지방의회: 의회별 월평균·항목 구성, 같은 직책 월평균 분포
    councils = []
    by_src = defaultdict(list)
    for e in exps:
        if e["source_id"] != "ka-money" and not e.get("duplicate_of") and e["date"]:
            by_src[e["source_id"]].append(e)
    for src, rows in by_src.items():
        # 공개 기간 밖 날짜(오기·OCR 오독)는 개월 수·기간 계산에 넣지 않는다
        months = {e["date"][:7] for e in rows if "DATE_OUTSIDE_REPORT_PERIOD" not in e["quality"]["flags"]}
        fund, cat = Counter(), Counter()
        for e in rows:
            fund[e["funding_type"]] += e["amount"]
            cat[e["category"]] += e["amount"]
        reg = registry.get(src, {})
        councils.append({"id": src, "name": reg.get("name", src), "level": reg.get("level"), "months": len(months),
                         "first": min(months), "last": max(months), "total": sum(fund.values()),
                         "monthly": sum(fund.values()) / max(len(months), 1),
                         "funding": [[k, v] for k, v in fund.most_common()], "categories": [[k, v] for k, v in cat.most_common()]})
    role_flag = {(f["period"]["label"][:4], f["subjectId"]): f["id"] for f in findings if f["ruleId"] == "ROLE_SPEND_OUTLIER"}
    import re as _re
    groups = {"의장": _re.compile(r"^의장$"), "부의장": _re.compile(r"^(제\d)?부의장$"), "상임위원장": _re.compile(r"위원장$")}
    role_rows = defaultdict(list)
    for sj in subjects:
        if sj["type"] != "COUNCIL_ROLE" or "예산결산" in (sj.get("role") or ""):
            continue
        g = next((k for k, rx in groups.items() if rx.search(sj.get("role") or "")), None)
        if not g:
            continue
        per_y = defaultdict(list)
        for e in by_src.get(sj["org_source"], []):
            if e["subject_id"] == sj["id"] and e["funding_type"] == "COUNCIL_OPERATION":
                per_y[e["date"][:4]].append(e)
        for y, ys in per_y.items():
            m = {e["date"][:7] for e in ys}
            if len(m) >= 6:
                role_rows[(g, y)].append([sj["id"], registry.get(sj["org_source"], {}).get("name", sj["org"]), sj["role"],
                                          sum(e["amount"] for e in ys) / len(m), len(m), registry.get(sj["org_source"], {}).get("level"),
                                          role_flag.get((y, sj["id"]))])
    roles = []
    for (g, y), items in sorted(role_rows.items(), key=lambda kv: (kv[0][1], list(groups).index(kv[0][0]))):
        base = [r[3] for r in items if r[5] == "기초"]
        if len(base) < 10:
            continue
        roles.append({"group": g, "year": y, "median": float(np.median(base)), "p95": float(np.percentile(base, 95)), "n": len(base),
                      "dots": sorted(items, key=lambda r: r[3])})
    return {"people": people, "legislators": leg, "councils": sorted(councils, key=lambda c: (c["level"] != "광역", c["name"])), "roles": roles}


def collection_status():
    out = {}
    ka = json.loads((RAW / "ka-money" / "manifest.json").read_text())
    out["ka-money"] = {"files": [{"name": m["filename"], "url": m["github_url"], "sha256": m["sha256"], "fetched_at": m["fetched_at"]}
                                 for m in ka if m["filename"].endswith(".xlsx")]}
    for src in load_registry():
        if not (RAW / src / "manifest.json").exists() or not (STAGING / f"{src}_parse_report.json").exists():
            continue
        manifest = json.loads((RAW / src / "manifest.json").read_text())
        report = json.loads((STAGING / f"{src}_parse_report.json").read_text())
        files = report if isinstance(report, list) else report.get("files", [])
        st = Counter(f.get("status", "parsed") for f in files)
        fetched = [a.get("fetched_at") for p in manifest for a in p["attachments"] if a.get("fetched_at")]
        ocr_rep = STAGING / f"{src}_ocr_report.json"
        ocr_files = json.loads(ocr_rep.read_text()).get("files", []) if ocr_rep.exists() else []
        ocr_ok = {f.get("file") for f in ocr_files if f.get("status") == "parsed"}
        out[src] = {
            "ocr": {"files": len(ocr_files), "parsed": len(ocr_ok), "rows": sum(f.get("rows") or 0 for f in ocr_files),
                    "totalChecked": sum(1 for f in ocr_files if f.get("total_check")),
                    "totalMatched": sum(1 for f in ocr_files if f.get("total_check") == "일치")} if ocr_files else None,
            "posts": len(manifest),
            "attachments": sum(len(p["attachments"]) for p in manifest),
            "status": dict(st),
            "fetchedAt": max(fetched) if fetched else None,
            "issues": [{"period": f.get("period"), "file": f.get("filename") or f.get("file"), "status": f.get("status"),
                        "reason": f.get("reason")} for f in files if f.get("status") not in (None, "parsed") and "명단" not in (f.get("filename") or "")
                       and (f.get("filename") or f.get("file")) not in ocr_ok][:80],
        }
    return out


def main():
    exps = read_jsonl(NORMALIZED / "expenditures.jsonl")
    subjects = json.loads((NORMALIZED / "subjects.json").read_text())
    merchants = {m["id"]: m for m in json.loads((NORMALIZED / "merchants.json").read_text())}
    documents = json.loads((NORMALIZED / "documents.json").read_text())
    funding = json.loads((NORMALIZED / "funding_types.json").read_text())
    findings = json.loads((NORMALIZED / "findings.json").read_text())
    pairs = json.loads((NORMALIZED / "reversal_pairs.json").read_text())
    rpairs = {v: k for k, v in pairs.items()}
    legal = json.loads((ROOT / "docs" / "legal-notes.json").read_text())
    asm_path = NORMALIZED / "assembly.json"
    assembly = json.loads(asm_path.read_text()) if asm_path.exists() else {"summary": None, "subjects": {}}
    asm = assembly["subjects"]
    sources = json.loads((ROOT / "docs" / "data-sources.json").read_text())
    exp_path = ROOT / "docs" / "expansion-candidates.json"
    expansion = json.loads(exp_path.read_text()) if exp_path.exists() else []

    # build_geo.py가 만든 geo.js는 남기고 이 스크립트가 만드는 파일만 지운다
    DATA.mkdir(parents=True, exist_ok=True)
    for sub in ("s", "m"):
        if (DATA / sub).exists():
            shutil.rmtree(DATA / sub)
    for f in ("meta.js", "findings-index.js", "merchant-index.js", "money.js", "fiscal.js", "rank.js", "assets.js"):
        (DATA / f).unlink(missing_ok=True)

    by_subject = defaultdict(list)
    by_merchant = defaultdict(list)
    for e in exps:
        by_subject[e["subject_id"]].append(e)
        if e.get("merchant_id") and not e.get("duplicate_of"):
            by_merchant[e["merchant_id"]].append(e)
    f_by_subject = defaultdict(list)
    for f in findings:
        f_by_subject[f["subjectId"]].append(f)

    # ---- subject shards
    subj_index = []
    sizes = 0
    for s in subjects:
        rows = by_subject.get(s["id"], [])
        if not rows:
            continue
        totals = defaultdict(lambda: [0, 0])
        doc_totals = defaultdict(lambda: [0, 0])
        for e in rows:
            if e.get("duplicate_of"):
                continue
            totals[e["funding_type"]][0] += 1
            totals[e["funding_type"]][1] += e["amount"]
            if e["source_id"] == "ka-money":
                doc_totals[e["doc_id"]][0] += 1
                doc_totals[e["doc_id"]][1] += e["amount"]
        dates = [e["date"] for e in rows if e["date"]]
        last = s.get("terms", {})
        latest_term = list(last.values())[-1] if last else {}
        subj_index.append({
            "id": s["id"], "name": s["name"], "type": s["type"], "org": s["org"], "source": rows[0]["source_id"],
            "role": s.get("role"), "term": s.get("term"), "termStart": s.get("term_start"), "termEnd": s.get("term_end"),
            "party": latest_term.get("party") or (s.get("precandidate") or {}).get("party"),
            "district": latest_term.get("district") or (s.get("precandidate") or {}).get("district"),
            "assemblies": list(last.keys()) if last else None,
            "districts": {k: v.get("district") for k, v in last.items()} if last else None,
            "precandidate": s.get("precandidate"),
            "docTotals": {k: {"count": v[0], "amount": v[1]} for k, v in doc_totals.items()} or None,
            "assembly": ({"committees": (asm[s["id"]].get("member") or {}).get("CMITS"),
                          "reelection": (asm[s["id"]].get("member") or {}).get("REELE_GBN_NM"),
                          "bills": {age: {"lead": b["lead"], "results": b["results"]} for age, b in asm[s["id"]]["bills"].items()},
                          "votes": {age: {"participation": v["participation"], "total": v["total"]} for age, v in (asm[s["id"]].get("votes") or {}).items()}}
                         if s["id"] in asm else None),
            "totals": {k: {"count": v[0], "amount": v[1]} for k, v in totals.items()},
            "first": min(dates) if dates else None, "last": max(dates) if dates else None,
            "findings": len(f_by_subject.get(s["id"], [])),
            "holders": [h["name"] for h in s.get("holders") or [] if h.get("name")] or None,
        })
        sizes += emit(DATA / "s" / f"{s['id']}.js", f"s:{s['id']}", {
            "subject": s,
            "assembly": asm.get(s["id"]),
            "ocr": rows[0]["quality"].get("ocr", False),
            "tx": encode([tx_row(e, pairs, rpairs) for e in rows], TX_COLS, DICT_COLS),
            "findings": f_by_subject.get(s["id"], []),
        })
    registry = load_registry()
    for org in registry:
        oid = f"org-{org}"
        sizes += emit(DATA / "s" / f"{oid}.js", f"s:{oid}", {"subject": {"id": oid, "type": "ORG", "name": oid},
                                                               "tx": encode([], TX_COLS, DICT_COLS), "findings": f_by_subject.get(oid, [])})
    print(f"subject shards: {len(subj_index)} ({sizes / 1e6:.1f} MB)", file=sys.stderr)

    # ---- merchant shards
    subj_names = {s["id"]: s["name"] for s in subjects}
    buckets = defaultdict(dict)
    merch_index = []
    for mid, rows in by_merchant.items():
        m = merchants[mid]
        subs = Counter(e["subject_id"] for e in rows)
        merch_index.append([mid, m["name"], len(rows), sum(e["amount"] for e in rows), m["id_confidence"], len(subs),
                            m["aliases"][:6], m.get("region")])
        buckets[djb2(mid)][mid] = {
            "merchant": m,
            "tx": encode([[e["id"], e["subject_id"], e["date"], e.get("time"), e["amount"], e.get("description"), e.get("category"),
                           e["funding_type"], e["doc_id"], e["source_id"],
                           None if e.get("payee_display") == m["name"] else e.get("payee_display")] for e in rows], M_COLS, M_DICT_COLS),
            "subjects": {sid: subj_names.get(sid, sid) for sid in subs},
        }
    msize = sum(emit(DATA / "m" / f"{b}.js", f"m:{b}", payload) for b, payload in buckets.items())
    merch_index.sort(key=lambda r: -r[2])
    emit(DATA / "merchant-index.js", "merchant-index", merch_index)
    print(f"merchant shards: {len(merch_index)} merchants in {len(buckets)} buckets ({msize / 1e6:.1f} MB)", file=sys.stderr)

    # ---- findings index (근거 id 목록 제외)
    f_index = [{k: f[k] for k in ("id", "ruleId", "code", "subjectId", "sourceId", "fundingType", "period", "evidenceCount",
                                  "reviewStatus", "explanation", "metric", "dataQuality")} for f in findings]
    emit(DATA / "findings-index.js", "findings-index", f_index)

    # ---- meta
    rule_counts = Counter(f["ruleId"] for f in findings)
    src_stats = {}
    for e in exps:
        if e.get("duplicate_of"):
            continue
        st = src_stats.setdefault(e["source_id"], {"count": 0, "first": "9999", "last": "0000", "byFunding": defaultdict(lambda: [0, 0]),
                                                   "subjects": set()})
        st["count"] += 1
        if e["date"] and "DATE_OUTSIDE_REPORT_PERIOD" not in e["quality"]["flags"]:
            st["first"], st["last"] = min(st["first"], e["date"]), max(st["last"], e["date"])
        st["byFunding"][e["funding_type"]][0] += 1
        st["byFunding"][e["funding_type"]][1] += e["amount"]
        st["subjects"].add(e["subject_id"])
    for st in src_stats.values():
        st["byFunding"] = {k: {"count": v[0], "amount": v[1]} for k, v in st["byFunding"].items()}
        st["subjects"] = len(st["subjects"])

    # 처음 화면의 예시: 1인당 식사비가 기준의 1.2배 이상인 거래 중 가장 최근 것
    # (선정 기준이 '최근'일 뿐 특정 주체를 지목하려는 것이 아님)
    by_id = {e["id"]: e for e in exps}
    example = None
    for f in findings:
        if f["ruleId"] != "MEAL_OVER_PER_PERSON_STANDARD":
            continue
        for tid in f["evidenceIds"]:
            e = by_id[tid]
            limit = 40000 if e["date"] < "2024-09-23" else 50000
            if e["amount"] / e["attendees"] < 1.2 * limit:
                continue
            if example is None or (e["date"], e.get("time") or "") > (example["tx"]["date"], example["tx"].get("time") or ""):
                example = {"findingId": f["id"], "subjectId": f["subjectId"], "subjectName": next(s["name"] for s in subjects if s["id"] == f["subjectId"]),
                           "limit": limit,
                           "tx": {"date": e["date"], "time": e.get("time"), "weekday": e.get("weekday"), "amount": e["amount"], "attendees": e["attendees"],
                                  "payee": e.get("payee_display"), "description": e.get("description"), "fundingType": e["funding_type"]}}
    reviews_path = ROOT / "data" / "reviews.json"
    reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}

    # 직책 보유자 → 사람 목록 (의회 공식 홈페이지 기준). 지출은 여전히 직책 단위이며 사람 페이지는 직책 이력을 모아 보여줄 뿐이다.
    people = {}
    for sj in subjects:
        for h in sj.get("holders") or []:
            if not h.get("name"):
                continue
            pid = f"{sj['org_source']}:{h['name']}"
            pr = people.setdefault(pid, {"id": pid, "source": sj["org_source"], "council": sj["org"], "name": h["name"],
                                         "party": h.get("party"), "partyNote": h.get("party_note"), "roles": [], "memberSubjects": []})
            pr["roles"].append({"subjectId": sj["id"], "role": sj["role"], "term": sj["term"], "start": h["period_start"],
                                "end": h["period_end"], "elected": h.get("elected"), "confidence": h["confidence"],
                                "sourceUrl": h["source_url"], "sourceTitle": h.get("source_title")})
    for sj in subjects:
        if sj["type"] == "COUNCIL_MEMBER":
            pid = f"{sj['org_source']}:{sj['role'][:-2]}"
            if pid in people:
                people[pid]["memberSubjects"].append(sj["id"])
    for pr in people.values():
        pr["roles"].sort(key=lambda r: r["start"])

    meta = {
        "assemblySummary": assembly["summary"],
        "councils": [{"id": k, **{f: v.get(f) for f in ("name", "region", "level", "board", "notes")}}
                     for k, v in registry.items() if k in src_stats],
        "example": example,
        "people": sorted(people.values(), key=lambda p: (p["source"], p["name"])),
        "reviews": reviews,
        "generatedAt": datetime.now(KST).isoformat(timespec="minutes"),
        "fundingTypes": funding,
        "rules": [{**r, "count": rule_counts.get(r["id"], 0)} for r in RULES],
        "notImplemented": NOT_IMPLEMENTED,
        "legal": legal,
        "sources": sources,
        "expansion": sorted(expansion, key=lambda d: d.get("recommended_priority") or 99),
        "collection": collection_status(),
        "documents": {d["doc_id"]: d for d in documents},
        "subjects": subj_index,
        "sourceStats": src_stats,
        "findingCount": len(findings),
        "merchantCount": len(merch_index),
    }
    fiscal_path = NORMALIZED / "fiscal.json"
    if fiscal_path.exists():
        emit(DATA / "fiscal.js", "fiscal", json.loads(fiscal_path.read_text()))
    money = build_money(exps, subjects, {s["id"]: s for s in subj_index}, findings, registry)
    msz = emit(DATA / "money.js", "money", money)
    print(f"money: {msz / 1e6:.2f} MB", file=sys.stderr)
    rsz = emit(DATA / "rank.js", "rank", build_rank(exps, subjects, merchants, registry))
    print(f"rank: {rsz / 1e6:.2f} MB", file=sys.stderr)
    assets = build_assets()
    if assets:
        asz = emit(DATA / "assets.js", "assets", assets)
        print(f"assets: {asz / 1e6:.2f} MB ({len(assets['people'])}명)", file=sys.stderr)
    size = emit(DATA / "meta.js", "meta", meta)
    print(f"meta: {size / 1e6:.2f} MB, findings: {len(findings)}", file=sys.stderr)


if __name__ == "__main__":
    main()
