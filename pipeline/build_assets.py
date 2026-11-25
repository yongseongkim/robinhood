"""build_site.py가 site/data/assets.js에 실을 국회의원 신고재산을 집계한다.

전세·임차권은 공보에서 ‘건물’로 신고하지만 소유 부동산과 구분해 집계한다.
자산 구분별 현재가액의 합에서 채무를 뺀 값이 공보의 총계와 일치하는지 확인한다.
"""
import json

from common import NORMALIZED

GROUP = {
    "토지": "부동산", "건물": "부동산", "예금": "예금", "정치자금 계좌": "정치자금 계좌", "증권": "증권", "채권": "채권", "현금": "현금",
    "가상자산": "가상자산", "자동차 등": "자동차 등", "채무": "채무",
}
GROUP_ORDER = ["부동산", "전세·임차권", "예금", "증권", "채권", "현금", "가상자산", "자동차 등", "정치자금 계좌", "기타", "채무"]
RE_COLS = ["person", "cat", "relation", "kind", "sido", "sgg", "emd", "area", "cur", "prev", "lease", "reason"]


def build_assets():
    path = NORMALIZED / "assets.json"
    if not path.exists():
        return None
    a = json.loads(path.read_text())
    people, realestate, mismatch = [], [], []
    for i, p in enumerate(a["people"]):
        groups = dict.fromkeys(GROUP_ORDER, 0)
        for cat, v in p["cats"].items():
            groups[GROUP.get(cat, "기타")] += v["cur"] or 0
        lease = sum(r["cur"] or 0 for r in p["realestate"] if r["lease"])
        groups["부동산"] -= lease
        groups["전세·임차권"] = lease
        if sum(v for k, v in groups.items() if k != "채무") - groups["채무"] != p["total"]["cur"]:
            mismatch.append(p["name"])
        owned = [r for r in p["realestate"] if not r["lease"] and (r["cur"] or 0) > 0]
        t = p["total"]
        people.append({
            "name": p["name"], "sid": p["sid"], "party": p["party"], "district": p["district"], "position": p["position"], "page": p["page"],
            "cur": t["cur"], "prev": t["prev"], "change": t["change"], "valuation": t["valuation"],
            "groups": [groups[g] for g in GROUP_ORDER], "owned": len(owned), "refused": p["refused"], "crypto": p["cryptoCount"],
        })
        for r in p["realestate"]:
            realestate.append([i, r["cat"], r["relation"], r["kind"], r["sido"], r["sgg"], r["emd"], ", ".join(r["area"]), r["cur"], r["prev"],
                               1 if r["lease"] else 0, r["reason"]])
    if mismatch:
        raise ValueError(f"재산 묶음 합계가 총계와 다름: {mismatch[:5]}")
    return {"source": a["source"], "groups": GROUP_ORDER, "people": people, "realestate": {"cols": RE_COLS, "rows": realestate}}
