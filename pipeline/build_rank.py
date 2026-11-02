"""'순위판' 화면용 집계 (build_site.py가 site/data/rank.js로 내보낸다)

- 공개 자료의 금액·건수·비율을 같은 재원·같은 기간 안에서만 줄 세운다. 탐지 결과로 매기는 점수는 없다.
- 국회의원: 정치자금, 연도별. 제21·22대 의원으로 확인된 주체만 넣는다.
- 지방의회: 의회운영업무추진비(직책 업무추진비)를 그 기간의 직책 보유자 이름으로 모은다.
  직책 수행 경비이고 결제는 비서실·사무국이 할 수 있으므로 개인 지출이라는 뜻이 아니다.
- 가게: 사업자 거래처만. 결제대행·배달앱처럼 실제 장소가 아닌 곳과 개인에게 지급된 금액은 넣지 않는다.
  전국 체인(스타벅스 등)은 지점이 여러 곳이라 '같은 장소'로 보지 않고, 식대로 분류됐어도 상호가 광고·여행사 등이면 식당 집계에서 뺀다.
- 가격 차이: 같은 식당에서 다른 결제들의 1인당 금액(중앙값)과 비교해 크게 비싼 결제. 시중가가 아니라 '그 가게의 평소 가격'이 기준이다.
- 다른 공개 파일에 다시 실린 같은 거래(duplicate_of)는 모두 뺀다.
"""
import re
from collections import Counter, defaultdict
from statistics import median

from common import COUNCIL_HOSPITALITY, KA_HOSPITALITY, is_chain, is_food_place, is_platform

TOP = 30          # 화면에는 10위까지 보이고 30위까지 펼쳐 볼 수 있다
MIN_MEALS = 20    # 평균·비율 순위에 넣을 최소 식사 건수
MIN_MONTHS = 6    # 월평균 순위에 넣을 최소 개월 수
YEARS = ("2023", "2024")
PRICE_MIN_MEALS = 8      # 가게의 '평소 1인당 금액'을 잡으려면 인원이 적힌 결제가 이만큼은 있어야 한다
PRICE_RATIO = 2.0        # 평소의 2배 이상이면서
PRICE_EXTRA = 15000      # 1인당 1만5천원 이상 비쌀 때
PRICE_BASE_MIN = 8000    # 평소 1인당 금액이 이보다 낮은 곳(식권·간식 위주)은 비교하지 않는다
# 1인당 비교가 맞지 않는 곳: 구내식당 식권·매점·도시락·케이터링은 한 번에 여러 명분을 사는 일이 많다
PRICE_SKIP = re.compile(r"구내식당|매점|식권|도시락|케이터링|쇼핑|백화점")
# 물품 내역에 수량이 적혀 있는지 (시중가 단가 비교가 가능한지 보여주기 위한 집계)
QUANTITY = re.compile(r"\d+\s*(개|박스|box|병|매|권|부|세트|set|ea|묶음|팩|캔|본|다발|켤레|장|통|봉|kg|명분)", re.I)
MEMBER_FUNDS = ("COUNCIL_OPERATION", "COUNCIL_COMMON", "NEGOTIATION_GROUP")
STAFF_FUNDS = ("INSTITUTION_OPERATION", "POLICY_PROMOTION", "DEPARTMENT_OPERATION")


def _board(rows, value_at, n=TOP, then=None):
    """rows를 value_at 열 기준으로 줄 세우고(같으면 then 열), 비교용 중앙값·대상 수를 붙인다."""
    rows = [r for r in rows if r[value_at] is not None]
    vals = [r[value_at] for r in rows]
    key = (lambda r: (-r[value_at], -r[then])) if then is not None else (lambda r: -r[value_at])
    return {"rows": sorted(rows, key=key)[:n], "median": median(vals) if vals else None, "n": len(rows)}


def _months(start, end):
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _is_place(e, merchants):
    mid = e.get("merchant_id")
    return bool(mid and e.get("payee_type") == "BUSINESS" and not is_platform(merchants[mid]["name"]))


def _weekend(e):
    return bool(e.get("is_weekend") or e.get("holiday"))


def _is_meal_place(e, merchants):
    return _is_place(e, merchants) and not is_chain(merchants[e["merchant_id"]]["name"]) and is_food_place(merchants[e["merchant_id"]]["name"])


def _food(e, merchants):
    """식대 분류 거래 중 상호로 보아 식당이 아닌 곳(광고·여행사 등)을 뺀다."""
    name = merchants[e["merchant_id"]]["name"] if e.get("merchant_id") else e.get("payee_display")
    return is_food_place(name)


def assembly_boards(exps, subjects, merchants):
    legis = {s["id"] for s in subjects if s["type"] == "LEGISLATOR" and s.get("terms")}
    out = {}
    for y in YEARS:
        total, count = Counter(), Counter()
        cats = defaultdict(Counter)
        meal_n, meal_amt, meal_wk = Counter(), Counter(), Counter()
        meal_places = defaultdict(Counter)
        for e in exps:
            sid = e["subject_id"]
            if e["source_id"] != "ka-money" or sid not in legis or not (e["date"] or "").startswith(y):
                continue
            total[sid] += e["amount"]
            count[sid] += 1
            if e.get("category"):
                cats[e["category"].split("_")[0]][sid] += e["amount"]
            if e.get("category") in KA_HOSPITALITY and e["amount"] > 0 and _food(e, merchants):
                meal_n[sid] += 1
                meal_amt[sid] += e["amount"]
                meal_wk[sid] += _weekend(e)
                if _is_meal_place(e, merchants):
                    meal_places[sid][e["merchant_id"]] += e["amount"]
        cat_order = sorted(cats, key=lambda c: -sum(cats[c].values()))
        top_place = []
        for sid, places in meal_places.items():
            if meal_n[sid] < MIN_MEALS:
                continue
            mid, amt = places.most_common(1)[0]
            top_place.append([sid, amt / sum(places.values()), mid, merchants[mid]["name"], amt])
        out[y] = {
            "total": _board([[sid, v, count[sid]] for sid, v in total.items() if v > 0], 1),
            "categories": {c: _board([[sid, v] for sid, v in cats[c].items() if v > 0], 1) for c in cat_order},
            "catOrder": cat_order,
            "mealCount": _board([[sid, n, meal_amt[sid]] for sid, n in meal_n.items()], 1),
            "mealAvg": _board([[sid, meal_amt[sid] / n, n] for sid, n in meal_n.items() if n >= MIN_MEALS], 1),
            "mealPlaces": _board([[sid, len(p), meal_n[sid]] for sid, p in meal_places.items()], 1),
            "mealTopPlace": _board(top_place, 1),
            "weekend": _board([[sid, meal_wk[sid] / n, meal_wk[sid], n] for sid, n in meal_n.items() if n >= MIN_MEALS], 1),
        }
    return out


def place_boards(exps, merchants, registry):
    """여러 사람이 함께 쓰는 가게와, 그 가게에서 가장 많이 쓴 주체."""
    ka_meal = defaultdict(lambda: {"n": 0, "amt": 0, "subs": Counter()})
    ka_vendor = defaultdict(lambda: {"n": 0, "amt": 0, "subs": Counter(), "cats": Counter()})
    c_meal = defaultdict(lambda: {"n": 0, "amt": 0, "subs": Counter(), "srcs": Counter(), "srcn": Counter()})
    c_vendor = defaultdict(lambda: {"n": 0, "amt": 0, "subs": Counter(), "srcs": Counter(), "cats": Counter()})
    ka_region, c_region = Counter(), Counter()
    for e in exps:
        if not _is_place(e, merchants):
            continue
        mid, ka = e["merchant_id"], e["source_id"] == "ka-money"
        meal = e.get("category") in (KA_HOSPITALITY if ka else COUNCIL_HOSPITALITY)
        if meal and not _is_meal_place(e, merchants):
            continue
        if ka:
            d = ka_meal[mid] if meal else ka_vendor[mid]
        else:
            d = c_meal[mid] if meal else c_vendor[mid]
            d["srcs"][e["source_id"]] += e["amount"]
            if "srcn" in d:
                d["srcn"][e["source_id"]] += 1
        d["n"] += 1
        d["amt"] += e["amount"]
        d["subs"][e["subject_id"]] += e["amount"]
        if not meal:
            d["cats"][e.get("category") or "기타"] += e["amount"]
        if meal:
            region = merchants[mid].get("region") or e.get("payee_region")
            if region:
                (ka_region if ka else c_region)[region] += e["amount"]

    def row(mid, d):
        m = merchants[mid]
        top_sid, top_amt = d["subs"].most_common(1)[0]
        r = [mid, m["name"], m.get("region"), len(d["subs"]), d["n"], d["amt"], top_sid, top_amt]
        if "srcs" in d:
            r.append(len(d["srcs"]))
        if "cats" in d:
            r.append(d["cats"].most_common(1)[0][0])
        return r

    ka_m = [row(k, d) for k, d in ka_meal.items() if d["amt"] > 0]
    ka_v = [row(k, d) for k, d in ka_vendor.items() if d["amt"] > 0]
    c_m = [row(k, d) for k, d in c_meal.items() if d["amt"] > 0]
    c_v = [row(k, d) for k, d in c_vendor.items() if d["amt"] > 0]
    per_council = defaultdict(list)
    for mid, d in c_meal.items():
        for src, amt in d["srcs"].items():
            subs = Counter({sid: v for sid, v in d["subs"].items() if sid.startswith(src + "-")})
            if amt > 0 and subs:
                top_sid, top_amt = subs.most_common(1)[0]
                per_council[src].append([mid, merchants[mid]["name"], merchants[mid].get("region"), len(subs), d["srcn"][src], amt, top_sid, top_amt])
    both = []
    for mid in set(ka_meal) & set(c_meal):
        k, c = ka_meal[mid], c_meal[mid]
        if k["amt"] > 0 and c["amt"] > 0:
            both.append([mid, merchants[mid]["name"], merchants[mid].get("region"), len(k["subs"]), k["amt"], len(c["srcs"]), c["amt"]])
    return {
        "kaMealByPeople": _board(ka_m, 3, then=5), "kaMealByAmount": _board(ka_m, 5),
        "kaVendorByPeople": _board(ka_v, 3, then=5), "kaVendorByAmount": _board(ka_v, 5),
        "councilMealByCouncils": _board([r for r in c_m if r[8] > 1], 8, then=5), "councilMealByAmount": _board(c_m, 5),
        "councilVendorByAmount": _board(c_v, 5),
        "perCouncil": {src: sorted(rows, key=lambda r: -r[5])[:10] for src, rows in per_council.items()},
        "both": sorted(both, key=lambda r: -(r[3] + r[5] * 10))[:TOP],
        "kaRegions": [[k, v] for k, v in ka_region.most_common(15)],
        "councilRegions": [[k, v] for k, v in c_region.most_common(15)],
        "counts": {"kaMeal": len(ka_m), "councilMeal": len(c_m)},
    }


def council_boards(exps, subjects, merchants, registry):
    by_src = defaultdict(list)
    for e in exps:
        if e["source_id"] != "ka-money" and e["date"]:
            by_src[e["source_id"]].append(e)
    # 공개 기간 밖 날짜(오기·OCR 오독)는 개월 수 계산에 넣지 않는다 (금액은 그대로 더한다)
    months_of = {src: {e["date"][:7] for e in rows if "DATE_OUTSIDE_REPORT_PERIOD" not in e["quality"]["flags"]} for src, rows in by_src.items()}

    councils = []
    for src, rows in by_src.items():
        reg = registry.get(src, {})
        n_months = len(months_of[src])
        member = sum(e["amount"] for e in rows if e["funding_type"] in MEMBER_FUNDS)
        staff = sum(e["amount"] for e in rows if e["funding_type"] in STAFF_FUNDS)
        meals = [e for e in rows if e.get("category") in COUNCIL_HOSPITALITY and e["amount"] > 0]
        with_att = [e for e in meals if e.get("attendees")]
        place_amt = Counter()
        for e in meals:
            if _is_meal_place(e, merchants):
                place_amt[e["merchant_id"]] += e["amount"]
        top_mid, top_amt = place_amt.most_common(1)[0] if place_amt else (None, 0)
        meal_total = sum(e["amount"] for e in meals)
        councils.append([
            src, reg.get("name", src), reg.get("level"), n_months, min(months_of[src]), max(months_of[src]),
            member / n_months, staff / n_months,
            (sum(e["amount"] for e in with_att) / sum(e["attendees"] for e in with_att)) if len(with_att) >= MIN_MEALS else None,
            (sum(_weekend(e) for e in meals) / len(meals)) if len(meals) >= MIN_MEALS else None,
            top_mid, merchants[top_mid]["name"] if top_mid else None, (top_amt / sum(place_amt.values())) if place_amt else None,
            len(place_amt), len(meals),
        ])

    # 직책 보유자(사람)별 의회운영업무추진비
    holders = {}
    for sj in subjects:
        if sj["type"] != "COUNCIL_ROLE" or not sj.get("holders"):
            continue
        src = sj["org_source"]
        rows = [e for e in by_src.get(src, []) if e["subject_id"] == sj["id"] and e["funding_type"] == "COUNCIL_OPERATION"]
        for h in sj["holders"]:
            if not h.get("name"):
                continue
            mine = [e for e in rows if h["period_start"] <= e["date"] <= h["period_end"]]
            tenure = set(_months(h["period_start"], h["period_end"])) & months_of.get(src, set())
            if not tenure:
                continue
            p = holders.setdefault((src, h["name"]), {"party": h.get("party"), "amt": 0, "n": 0, "months": set(), "roles": [], "sids": []})
            p["amt"] += sum(e["amount"] for e in mine)
            p["n"] += len(mine)
            p["months"] |= tenure
            p["roles"].append(f"{sj['role']} ({sj['term']})")
            p["sids"].append(sj["id"])
    people = [[src, name, p["party"], p["amt"], p["n"], len(p["months"]), p["amt"] / len(p["months"]), p["roles"], p["sids"],
               registry.get(src, {}).get("level")]
              for (src, name), p in holders.items() if p["amt"] > 0]

    # 직책·기수별 의회운영업무추진비 (보유자 기록이 없는 의회도 포함)
    roles = []
    for sj in subjects:
        if sj["type"] != "COUNCIL_ROLE" or not sj.get("term_start"):
            continue
        src = sj["org_source"]
        mine = [e for e in by_src.get(src, []) if e["subject_id"] == sj["id"] and e["funding_type"] == "COUNCIL_OPERATION"]
        if not mine:
            continue
        span = set(_months(sj["term_start"], sj["term_end"] or max(months_of[src]) + "-28")) & months_of[src]
        if len(span) < MIN_MONTHS:
            continue
        amt = sum(e["amount"] for e in mine)
        roles.append([sj["id"], src, amt, len(mine), len(span), amt / len(span),
                      [h["name"] for h in sj.get("holders") or [] if h.get("name")], registry.get(src, {}).get("level")])
    return {"councils": sorted(councils, key=lambda r: -r[6]), "people": sorted(people, key=lambda r: -r[6]),
            "roles": sorted(roles, key=lambda r: -r[5]), "holderCouncils": sorted({p[0] for p in people})}


def price_gaps(exps, merchants):
    """같은 식당의 평소 1인당 금액보다 크게 비싼 결제 (지방의회, 인원이 적힌 식사만. OCR로 읽은 행은 인원 오독 위험이 있어 뺀다)."""
    per = defaultdict(list)
    for e in exps:
        if (e["source_id"] == "ka-money" or e.get("category") != "식사" or e["amount"] <= 0 or not e.get("attendees")
                or "OCR_EXTRACTED" in e["quality"]["flags"] or not _is_meal_place(e, merchants)
                or PRICE_SKIP.search(merchants[e["merchant_id"]]["name"])):
            continue
        per[e["merchant_id"]].append(e)
    rows, by_sid, checked = [], defaultdict(lambda: [0, 0, 0]), 0
    for mid, es in per.items():
        if len(es) < PRICE_MIN_MEALS:
            continue
        base = median(e["amount"] / e["attendees"] for e in es)
        if base < PRICE_BASE_MIN:
            continue
        checked += len(es)
        for e in es:
            pp = e["amount"] / e["attendees"]
            by_sid[e["subject_id"]][2] += 1
            if pp >= PRICE_RATIO * base and pp - base >= PRICE_EXTRA:
                rows.append([e["id"], e["subject_id"], e["date"], mid, merchants[mid]["name"], e["amount"], e["attendees"], pp, base, pp / base, len(es)])
                b = by_sid[e["subject_id"]]
                b[0] += 1
                b[1] += (pp - base) * e["attendees"]
    goods = [e for e in exps if e["source_id"] != "ka-money" and e.get("category") == "물품·구매" and e["amount"] > 0]
    rows.sort(key=lambda r: -r[9])
    subjects = [[sid, n, extra, total] for sid, (n, extra, total) in by_sid.items() if n]
    return {"tx": rows[:60], "count": len(rows), "checked": checked,
            "venues": sum(1 for es in per.values() if len(es) >= PRICE_MIN_MEALS and median(e["amount"] / e["attendees"] for e in es) >= PRICE_BASE_MIN),
            "bySubject": _board(subjects, 2),
            "goods": {"count": len(goods), "withQuantity": sum(1 for e in goods if QUANTITY.search(e.get("description") or ""))}, "params": {"minMeals": PRICE_MIN_MEALS, "ratio": PRICE_RATIO, "extra": PRICE_EXTRA, "baseMin": PRICE_BASE_MIN}}


def build_rank(exps, subjects, merchants, registry):
    exps = [e for e in exps if not e.get("duplicate_of")]
    return {
        "assembly": assembly_boards(exps, subjects, merchants),
        "council": council_boards(exps, subjects, merchants, registry),
        "places": place_boards(exps, merchants, registry),
        "price": price_gaps(exps, merchants),
        "params": {"top": TOP, "minMeals": MIN_MEALS, "minMonths": MIN_MONTHS},
    }
