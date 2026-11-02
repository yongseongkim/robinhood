"""이상 패턴 탐지 → data/normalized/findings.json

원칙
- 탐지 결과는 '추가 확인이 필요한 패턴'이며 위반·부정의 증거가 아니다.
- 지출 주체(의원·직책)에 점수를 매기지 않는다. 규칙별·거래 단위 근거만 남긴다.
- 서로 다른 재원(정치자금 / 업무추진비 / 공통경비)은 같은 비교집단에 섞지 않는다.
- 비교 표본이 기준보다 작으면 비교를 생략한다.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

import numpy as np

from common import (CHAIN_STORE, KA_HOSPITALITY, NORMALIZED, RAW, STAGING, clean_text, is_hospitality, is_platform, parse_period,
                    period_range, read_jsonl, short_hash, write_json)
from councils import jurisdiction_areas, load_registry
from rules import RULES_BY_ID

REGISTRY = load_registry()
COUNCILS = {k: v["name"] for k, v in REGISTRY.items()}
INSTITUTIONAL_MERCHANT = re.compile(r"국회|후생복지|구내식당|의원회관|청사|구청|공단|공사$")
EVIDENCE_CAP = 300


def n_rejected(r):
    v = r.get("rejected_rows")
    return len(v) if isinstance(v, list) else int(v or 0)


def won(n):
    return f"{int(round(n)):,}원"


class Detector:
    def __init__(self, exps, subjects, merchants):
        # 다른 공개 파일에 다시 실린 행(duplicate_of)은 중복 거래 규칙에서만 보고, 나머지 규칙·합계에서는 뺀다
        self.all_exps = exps
        self.by_id = {e["id"]: e for e in exps}
        exps = [e for e in exps if not e.get("duplicate_of")]
        self.exps = exps
        self.subjects = {s["id"]: s for s in subjects}
        self.merchants = {m["id"]: m for m in merchants}
        self.findings = []
        self.doc_format = {}
        self.by_subject = defaultdict(list)
        for e in exps:
            self.by_subject[e["subject_id"]].append(e)

    # ------------------------------------------------------------------ helpers
    def add(self, rule_id, subject_id, source_id, evidence, observed, reference, explanation,
            period=None, funding_type=None, review="NEEDS_CONTEXT", metric=None, extra=None):
        rule = RULES_BY_ID[rule_id]
        ev = sorted({e["id"] if isinstance(e, dict) else e for e in evidence},
                    key=lambda i: (self.by_id[i]["date"] or "", self.by_id[i].get("time") or "") if i in self.by_id else ("", ""))
        if period is None and ev:
            ds = [self.by_id[i]["date"] for i in ev if i in self.by_id and self.by_id[i]["date"]]
            period = {"start": min(ds), "end": max(ds)} if ds else None
        f = {
            "id": f"{rule['code']}-{short_hash(rule_id, subject_id, *ev[:50], json.dumps(period, sort_keys=True), n=12)}",
            "ruleId": rule_id,
            "code": rule["code"],
            "subjectId": subject_id,
            "sourceId": source_id,
            "fundingType": funding_type,
            "period": period,
            "observed": observed,
            "reference": reference,
            "evidenceIds": ev[:EVIDENCE_CAP],
            "evidenceCount": len(ev),
            "dataQuality": self.data_quality(source_id, ev),
            "reviewStatus": review,
            "explanation": explanation,
            "legalRefs": rule["legal_refs"],
            "metric": metric,
        }
        if extra:
            f.update(extra)
        self.findings.append(f)

    def subj_name(self, sid):
        s = self.subjects.get(sid)
        if not s:
            return sid
        return f"{s['name']} 의원" if s["type"] == "LEGISLATOR" else s["name"]

    @staticmethod
    def year_groups(rows):
        g = defaultdict(list)
        for e in rows:
            g[e["date"][:4]].append(e)
        return g

    # ------------------------------------------------------------------ A1
    def meal_over_standard(self):
        cut = date(2024, 9, 23)
        groups = defaultdict(list)
        for e in self.exps:
            if e["source_id"] == "ka-money" or not e.get("attendees") or e["amount"] <= 0:
                continue
            if e["category"] not in ("식사", "간담회(업종 미확인)"):
                continue
            limit = 40000 if date.fromisoformat(e["date"]) < cut else 50000
            pp = e["amount"] / e["attendees"]
            if pp > limit:
                groups[(e["subject_id"], e["date"][:4])].append((e, pp, limit))
        for (sid, year), items in groups.items():
            e0 = items[0][0]
            worst = max(items, key=lambda x: x[1] / x[2])
            self.add(
                "MEAL_OVER_PER_PERSON_STANDARD", sid, e0["source_id"], [x[0] for x in items],
                observed={"transactionCount": len(items), "maxPerPerson": round(worst[1]),
                          "maxRatio": round(worst[1] / worst[2], 2), "totalAmount": sum(x[0]["amount"] for x in items)},
                reference={"type": "REGULATORY", "value": "1인 1회 40,000원(2024-09-22까지) / 50,000원(2024-09-23부터)",
                           "description": "지방자치단체 회계관리에 관한 훈령 별표 2의2 — 사유를 증빙서류에 적으면 초과 집행 가능"},
                explanation=f"{year}년 {self.subj_name(sid)}의 간담회 식사 {len(items)}건이 1인당 기준 금액을 넘었습니다. "
                            f"가장 큰 경우 1인당 {won(worst[1])}(기준 {won(worst[2])}). 훈령은 사유를 적으면 초과를 허용하므로, 증빙서류의 사유 기재 여부를 확인해야 합니다.",
                period={"start": f"{year}-01-01", "end": f"{year}-12-31", "label": f"{year}년"},
                funding_type=e0["funding_type"], metric=len(items),
            )

    def ka_high_meal(self):
        rows = [e for e in self.exps if e["source_id"] == "ka-money" and e["category"] in KA_HOSPITALITY and e["amount"] > 0 and e["date"]]
        cats = defaultdict(list)
        for e in rows:
            cats[(e["category"], e["date"][:4])].append(e["amount"])
        p99 = {k: float(np.percentile(v, 99)) for k, v in cats.items() if len(v) >= 200}
        groups = defaultdict(list)
        for e in rows:
            k = (e["category"], e["date"][:4])
            if k in p99 and e["amount"] >= p99[k]:
                groups[(e["subject_id"], e["date"][:4])].append(e)
        for (sid, y), items in groups.items():
            top = max(items, key=lambda e: e["amount"])
            self.add(
                "KA_HIGH_MEAL_AMOUNT", sid, "ka-money", items,
                observed={"transactionCount": len(items), "maxAmount": top["amount"], "totalAmount": sum(e["amount"] for e in items)},
                reference={"type": "STATISTICAL", "description": f"{y}년 전체 의원의 같은 분류 식대 결제 금액 99백분위수",
                           "thresholds": {c: round(v) for (c, yy), v in p99.items() if yy == y},
                           "sampleSize": {c: len(cats[(c, yy)]) for (c, yy) in p99 if yy == y}},
                explanation=f"{y}년 {self.subj_name(sid)} 정치자금의 식대 결제 {len(items)}건이 그해 전체 의원 식대 결제 상위 1% 금액 이상입니다"
                            f"(최대 {won(top['amount'])}, {top['payee_display'] or '사용처 미상'}). 참석 인원이 공개되지 않아 1인당 금액은 알 수 없습니다.",
                period={"start": f"{y}-01-01", "end": f"{y}-12-31", "label": f"{y}년"},
                funding_type="POLITICAL_FUND", metric=top["amount"],
            )

    # ------------------------------------------------------------------ A2 / B2
    def hospitality_rows(self, sid):
        return [e for e in self.by_subject[sid] if is_hospitality(e) and e["amount"] > 0 and e.get("merchant_id")
                and not is_platform(e.get("payee_raw"))]

    def repeated_merchant(self):
        for sid in self.by_subject:
            rows = self.hospitality_rows(sid)
            if len(rows) < 20:
                continue
            total = sum(e["amount"] for e in rows)
            per_m = defaultdict(list)
            for e in rows:
                per_m[e["merchant_id"]].append(e)
            for mid, items in per_m.items():
                m = self.merchants[mid]
                if INSTITUTIONAL_MERCHANT.search(m["name"]):
                    continue
                days = sorted(date.fromisoformat(e["date"]) for e in items)
                max90, j = 0, 0
                for i in range(len(days)):
                    while days[i] - days[j] > timedelta(days=89):
                        j += 1
                    max90 = max(max90, i - j + 1)
                amt = sum(e["amount"] for e in items)
                share = amt / total if total else 0
                if (len(items) >= 10 and share >= 0.25) or (max90 >= 8 and share >= 0.05):
                    e0 = items[0]
                    self.add(
                        "REPEATED_MERCHANT", sid, e0["source_id"], items,
                        observed={"transactionCount": len(items), "totalAmount": amt, "merchantShare": round(share, 3),
                                  "max90DayCount": max90, "merchantId": mid, "merchantName": m["name"],
                                  "merchantIdConfidence": m["id_confidence"]},
                        reference={"type": "STATISTICAL", "description": "같은 주체의 식사·다과 지출 전체",
                                   "sampleSize": len(rows), "subjectHospitalityTotal": total},
                        explanation=f"{self.subj_name(sid)}의 식사·다과 지출 {len(rows)}건 중 {len(items)}건({share:.0%}, {won(amt)})이 "
                                    f"'{m['name']}'에서 결제되었습니다. 90일 안에 최대 {max90}회 이용했습니다. 이용 사유와 업소와의 관계는 공개자료로 확인할 수 없습니다.",
                        funding_type=e0["funding_type"], metric=share,
                        extra={"merchantId": mid},
                    )

    def merchant_concentration(self):
        stats = defaultdict(list)
        for sid in self.by_subject:
            rows = self.hospitality_rows(sid)
            if len(rows) < 30:
                continue
            per_m = Counter()
            for e in rows:
                per_m[e["merchant_id"]] += e["amount"]
            total = sum(per_m.values())
            if total <= 0:
                continue
            top3 = per_m.most_common(3)
            share3 = sum(v for _, v in top3) / total
            hhi = sum((v / total) ** 2 for v in per_m.values())
            stats[rows[0]["source_id"]].append((sid, share3, hhi, top3, total, len(rows), len(per_m)))
        for src, items in stats.items():
            if len(items) < 20:
                continue
            p95 = float(np.percentile([x[1] for x in items], 95))
            for sid, share3, hhi, top3, total, n, nm in items:
                if share3 >= p95:
                    names = [self.merchants[m]["name"] for m, _ in top3]
                    ev = [e for e in self.hospitality_rows(sid) if e["merchant_id"] in {m for m, _ in top3}]
                    self.add(
                        "TOP_MERCHANT_CONCENTRATION", sid, src, ev,
                        observed={"top3Share": round(share3, 3), "hhi": round(hhi, 3), "merchantCount": nm, "transactionCount": n,
                                  "top3": [{"merchantId": m, "name": self.merchants[m]["name"], "amount": v} for m, v in top3]},
                        reference={"type": "STATISTICAL", "description": f"같은 출처 주체 {len(items)}곳의 상위 3곳 비중 95백분위수",
                                   "value": round(p95, 3), "sampleSize": len(items)},
                        explanation=f"{self.subj_name(sid)}의 식사·다과 지출 {won(total)} 중 {share3:.0%}가 상위 3개 거래처({', '.join(names)})에 몰려 있습니다. "
                                    f"비교 대상 {len(items)}곳 중 상위 5% 수준입니다.",
                        funding_type=ev[0]["funding_type"] if ev else None, metric=share3,
                    )

    # ------------------------------------------------------------------ A3
    def restricted_hours_days(self):
        hours, days = defaultdict(list), defaultdict(list)
        for e in self.exps:
            if e["source_id"] == "ka-money" or e["amount"] <= 0:
                continue
            # 경조사·성금은 행사일·납부일 기준이고, 온라인 결제 시각은 '사용' 시각이 아니다
            if e["category"] in ("경조사", "성금·회비·격려금") or is_platform(e.get("payee_raw")):
                continue
            y = e["date"][:4]
            t = e.get("time")
            if t and (t >= "23:00" or t < "06:00"):
                hours[(e["subject_id"], y)].append(e)
            if e["is_weekend"] or e["holiday"]:
                days[(e["subject_id"], y)].append(e)
        for (sid, y), items in hours.items():
            self.add(
                "RESTRICTED_HOURS", sid, items[0]["source_id"], items,
                observed={"transactionCount": len(items), "totalAmount": sum(e["amount"] for e in items),
                          "times": sorted({e["time"] for e in items})},
                reference={"type": "REGULATORY", "value": "23:00~06:00", "description": "회계관리 훈령 별표 2의2 — 직무 관련성 증빙 시 사용 가능"},
                explanation=f"{y}년 {self.subj_name(sid)}의 업무추진비 {len(items)}건이 23시~6시 사이에 결제되었습니다. "
                            f"훈령은 이 시간대 사용을 제한하되 직무 관련성 증빙이 있으면 허용합니다.",
                period={"start": f"{y}-01-01", "end": f"{y}-12-31", "label": f"{y}년"},
                funding_type=items[0]["funding_type"], metric=len(items),
            )
        for (sid, y), items in days.items():
            hol = Counter(e["holiday"] or ("토요일" if e["weekday"] == "토" else "일요일") for e in items)
            total_n = sum(1 for e in self.by_subject[sid] if e["date"][:4] == y)
            self.add(
                "RESTRICTED_DAYS", sid, items[0]["source_id"], items,
                observed={"transactionCount": len(items), "totalAmount": sum(e["amount"] for e in items),
                          "shareOfTransactions": round(len(items) / total_n, 3) if total_n else None, "byDayType": dict(hol)},
                reference={"type": "REGULATORY", "value": "토·일요일 및 법정공휴일", "description": "회계관리 훈령 별표 2의2 — 직무 관련성 증빙 시 사용 가능"},
                explanation=f"{y}년 {self.subj_name(sid)}의 업무추진비 {len(items)}건({won(sum(e['amount'] for e in items))})이 주말·공휴일에 결제되었습니다. "
                            f"주말 행사 등 직무 관련성 증빙이 있으면 허용되므로, 해당 일자의 공식 일정과 대조가 필요합니다.",
                period={"start": f"{y}-01-01", "end": f"{y}-12-31", "label": f"{y}년"},
                funding_type=items[0]["funding_type"], metric=len(items),
            )

    def ka_weekend_share(self):
        by_year = defaultdict(list)
        for sid, rows in self.by_subject.items():
            if not sid.startswith("na-"):
                continue
            per_y = defaultdict(list)
            for e in rows:
                if e["category"] in KA_HOSPITALITY and e["amount"] > 0 and e["date"]:
                    per_y[e["date"][:4]].append(e)
            for y, h in per_y.items():
                if len(h) >= 20:
                    wk = [e for e in h if e["is_weekend"] or e["holiday"]]
                    by_year[y].append((sid, len(wk) / len(h), wk, len(h)))
        for y, stats in by_year.items():
            self._weekend_share_year(y, stats)

    def _weekend_share_year(self, y, stats):
        if len(stats) < 50:
            return
        shares = [s[1] for s in stats]
        p95, med = float(np.percentile(shares, 95)), float(np.median(shares))
        for sid, share, wk, n in stats:
            if share >= p95 and wk:
                self.add(
                    "KA_WEEKEND_HOSPITALITY_SHARE", sid, "ka-money", wk,
                    observed={"weekendHolidayShare": round(share, 3), "weekendHolidayCount": len(wk), "hospitalityCount": n,
                              "totalAmount": sum(e["amount"] for e in wk)},
                    reference={"type": "STATISTICAL", "description": f"{y}년 식사·다과 20건 이상 의원 {len(stats)}명의 주말·공휴일 비중",
                               "value": round(p95, 3), "median": round(med, 3), "sampleSize": len(stats)},
                    explanation=f"{y}년 {self.subj_name(sid)}의 식사·다과 지출 {n}건 중 {share:.0%}가 주말·공휴일입니다(의원 중앙값 {med:.0%}). "
                                f"지역구 주말 활동은 국회의원의 통상 업무일 수 있어, 그 자체로 문제라는 뜻은 아닙니다.",
                    period={"start": f"{y}-01-01", "end": f"{y}-12-31", "label": f"{y}년"},
                    funding_type="POLITICAL_FUND", metric=share,
                )

    # ------------------------------------------------------------------ A4
    def same_day_split(self):
        g = defaultdict(list)
        for e in self.exps:
            if is_hospitality(e) and e["amount"] > 0 and e.get("merchant_id") and e["date"] and not is_platform(e.get("payee_raw")):
                g[(e["subject_id"], e["date"], e["merchant_id"])].append(e)
        per_subject = defaultdict(list)
        for (sid, d, mid), items in g.items():
            if len(items) < 2:
                continue
            amts = sorted(e["amount"] for e in items)
            crosses = sum(amts) >= 500000 and amts[-1] < 500000
            if amts[0] / amts[-1] < 0.5 and not crosses:
                continue  # 큰 결제 뒤의 소액 추가 주문은 분할 결제 패턴이 아니다
            times = sorted(e["time"] for e in items if e.get("time"))
            if len(times) == len(items):
                mins = [int(t[:2]) * 60 + int(t[3:]) for t in times]
                gaps = [b - a for a, b in zip(mins, mins[1:])]
                if min(gaps) > 60:
                    continue
                gap = min(gaps)
            else:
                gap = None
            per_subject[sid].append((d, mid, items, gap))
        for sid, groups in per_subject.items():
            src = groups[0][2][0]["source_id"]
            around500 = [x for x in groups if sum(e["amount"] for e in x[2]) >= 500000 and all(e["amount"] < 500000 for e in x[2])]
            ev = [e for x in groups for e in x[2]]
            detail = [{"date": d, "merchantId": mid, "merchantName": self.merchants[mid]["name"], "count": len(items),
                       "total": sum(e["amount"] for e in items), "minGapMinutes": gap,
                       "crosses500k": sum(e["amount"] for e in items) >= 500000 and all(e["amount"] < 500000 for e in items),
                       "ids": [e["id"] for e in items]} for d, mid, items, gap in sorted(groups, key=lambda x: (x[0], x[1]))]
            no_time = sum(1 for x in groups if x[3] is None)
            self.add(
                "SAME_DAY_SPLIT", sid, src, ev,
                observed={"occurrences": len(groups), "transactionCount": len(ev), "crosses500kCount": len(around500),
                          "withoutTimeInfo": no_time, "groups": detail[:100]},
                reference={"type": "EXACT_MATCH", "description": "같은 날·같은 업소 2건 이상 (시간 정보가 있으면 60분 이내)"},
                explanation=f"{self.subj_name(sid)}의 지출에서 같은 날 같은 업소에 2번 이상 결제한 경우가 {len(groups)}번 있습니다"
                            + (f"(그중 {len(around500)}번은 각 건은 50만원 미만이지만 합계가 50만원 이상)" if around500 else "")
                            + ". 추가 주문·테이블별 계산 등 정상적인 사례도 많아 영수증 확인이 필요합니다.",
                funding_type=ev[0]["funding_type"], metric=len(groups),
            )

    # ------------------------------------------------------------------ A5
    SECTOR_KEYWORDS = [
        ("유흥", re.compile(r"룸살롱|룸싸롱|단란|가라오케|가요주점|나이트|카바레|스탠드바|유흥|극장식")),
        ("위생", re.compile(r"미용실|헤어|네일|피부관리|마사지|안마|사우나|찜질|에스테틱|이발|지압")),
        ("레저", re.compile(r"골프|노래방|노래연습장|코인노래|당구장|당구클럽|헬스장|헬스클럽|피트니스|pc방|피씨방|볼링장|스키장")),
        ("사행", re.compile(r"카지노|복권|경마|오락실")),
        ("주류 주목적 의심", re.compile(r"호프|포차|포장마차|이자카야|주점|와인바|칵테일|비어|맥주|펍|pub|\bbar\b|술집|막걸리|소주")),
    ]

    def restricted_sector(self):
        g = defaultdict(list)
        for e in self.exps:
            if e["source_id"] == "ka-money" or not e.get("payee_raw") or e["amount"] <= 0:
                continue
            name = (clean_text(e["payee_raw"]) or "").lower()
            for label, rx in self.SECTOR_KEYWORDS:
                m = rx.search(name)
                if m:
                    g[(e["subject_id"], e.get("merchant_id") or name, label, m.group(0))].append(e)
                    break
        for (sid, mid, label, kw), items in g.items():
            mname = items[0]["payee_raw"]
            self.add(
                "RESTRICTED_SECTOR_KEYWORD", sid, items[0]["source_id"], items,
                observed={"transactionCount": len(items), "totalAmount": sum(e["amount"] for e in items), "sector": label,
                          "keyword": kw, "merchantName": mname},
                reference={"type": "KEYWORD", "description": "클린카드 의무 제한업종(회계관리 훈령 별표 4) 및 주류 주목적 업종(별표 2의2)"},
                explanation=f"{self.subj_name(sid)}의 업무추진비가 상호명에 '{kw}'가 들어간 '{mname}'에서 {len(items)}건 결제되었습니다. "
                            f"상호명만으로는 실제 업종({label})을 확정할 수 없어 가맹점 업종코드 확인이 필요합니다.",
                funding_type=items[0]["funding_type"], metric=len(items),
                extra={"merchantId": mid if isinstance(mid, str) and mid[:1] in "bn" else None},
            )

    PRIVATE_KEYWORDS = re.compile(
        r"향우회|동창회|동문회|종친회|화수회|산악회|동호회|계모임|골프|스크린골프|헬스장|헬스클럽|피트니스|필라테스|요가|미용실|헤어샵|네일|피부과|피부관리|"
        r"마사지|사우나|찜질|가족여행|가족모임|자녀|생활비|노래방|노래연습장"
    )

    def private_expense_keyword(self):
        g = defaultdict(list)
        for e in self.exps:
            if e["source_id"] != "ka-money" or e["amount"] <= 0:
                continue
            if e["category"] in ("사무실_임대료및관리비", "사무실_보증금", "사무실_숙소관련비용"):
                continue  # 건물주(종친회·사우나 등)에게 낸 임대료는 사적 경비 유형과 무관
            if "주차" in (e.get("description") or ""):
                continue  # 골프장 등 건물 주차장 이용료
            text = f"{e.get('description') or ''} {e.get('payee_raw') or ''}"
            m = self.PRIVATE_KEYWORDS.search(text)
            if m:
                g[e["subject_id"]].append((e, m.group(0)))
        for sid, items in g.items():
            kws = Counter(k for _, k in items)
            self.add(
                "PRIVATE_EXPENSE_KEYWORD", sid, "ka-money", [e for e, _ in items],
                observed={"transactionCount": len(items), "totalAmount": sum(e["amount"] for e, _ in items), "keywords": dict(kws)},
                reference={"type": "KEYWORD", "description": "정치자금법 제2조 제3항의 사적 경비 유형(사적 모임 회비, 개인 여가·취미 등)"},
                explanation=f"{self.subj_name(sid)} 정치자금 지출 {len(items)}건의 내역·사용처에 "
                            f"{', '.join(f'‘{k}’' for k in list(kws)[:5])} 등 사적 경비 유형과 겹치는 단어가 있습니다. "
                            f"단어 일치일 뿐, 정치활동 관련 지출인지는 원본과 목적을 확인해야 합니다.",
                funding_type="POLITICAL_FUND", metric=len(items),
            )

    NON_FOOD = re.compile(r"주유|오일뱅크|에너지|칼텍스|s-oil|에쓰오일|통신(?!판매)|텔레콤|서적|도서|문고|서점|의류|패션|약국|화훼|꽃집|꽃배달|플라워|안경|가전|가구|인쇄")

    def purpose_mismatch(self):
        g = defaultdict(list)
        for e in self.exps:
            if e["source_id"] != "ka-money" or e["category"] not in KA_HOSPITALITY or e["amount"] <= 0:
                continue
            biz, name = (e.get("biztype_raw") or "").lower(), (e.get("payee_raw") or "").lower()
            if is_platform(name):
                continue  # 카드 단말기(VAN)·결제대행사 명의는 실제 업소가 아님
            m = self.NON_FOOD.search(biz) or self.NON_FOOD.search(name)
            if m and not re.search(r"식당|음식|카페|커피|레스토랑|푸드", biz + name):
                g[e["subject_id"]].append((e, m.group(0), "업종" if self.NON_FOOD.search(biz) else "상호명"))
        for sid, items in g.items():
            self.add(
                "PURPOSE_MERCHANT_MISMATCH", sid, "ka-money", [e for e, _, _ in items],
                observed={"transactionCount": len(items), "totalAmount": sum(e["amount"] for e, _, _ in items),
                          "matchedOn": dict(Counter(s for _, _, s in items)), "keywords": dict(Counter(k for _, k, _ in items))},
                reference={"type": "KEYWORD", "description": "식대·다과 분류 vs 보고서 업종 칸·상호명의 비음식 업종 단어"},
                explanation=f"{self.subj_name(sid)} 정치자금 중 식대·다과로 분류된 {len(items)}건의 거래처 업종·상호가 비음식 업종으로 보입니다. "
                            f"오마이뉴스의 분류나 OCR 오류일 수 있어 원본 확인이 필요합니다.",
                funding_type="POLITICAL_FUND", metric=len(items),
            )

    def cash_payment(self):
        g = defaultdict(list)
        for e in self.exps:
            if e["source_id"] == "ka-money" or e["amount"] <= 0:
                continue
            if "현금" in (e.get("payment_method") or "") and e["category"] not in ("경조사", "성금·회비·격려금"):
                g[(e["subject_id"], e["date"][:4])].append(e)
        for (sid, y), items in g.items():
            self.add(
                "CASH_PAYMENT", sid, items[0]["source_id"], items,
                observed={"transactionCount": len(items), "totalAmount": sum(e["amount"] for e in items)},
                reference={"type": "REGULATORY", "description": "회계관리 훈령 별표 2의2 — 업무추진비는 원칙적으로 현금 사용 불가"},
                explanation=f"{y}년 {self.subj_name(sid)}의 업무추진비 {len(items)}건이 현금으로 집행되었습니다(경조사 분류 제외). 현금 사용 사유 확인이 필요합니다.",
                period={"start": f"{y}-01-01", "end": f"{y}-12-31", "label": f"{y}년"},
                funding_type=items[0]["funding_type"], metric=len(items),
            )

    # 전국 체인은 카드 가맹점 주소가 본사로 찍히는 경우가 많아(예: 스타벅스 코리아 → 서울 중구) 지역 판단에서 뺀다
    CHAIN = CHAIN_STORE
    # 근무지와 경계를 접한 시·군·구까지 (훈령 별표 2의2). 주소가 공개된 의회만 해당된다.
    # 광역의회(서울특별시의회)는 훈령에 범위가 없어 시·도 + 경계를 접한 시·군을 준용한다(해석). councils.py 참고.
    AREA = jurisdiction_areas(REGISTRY)
    AREA_LABEL = {k: (v["region"] + "·인접 시" if " " not in v["region"] else v["region"].split()[1] + "·인접 지역") for k, v in REGISTRY.items()}
    ONLINE = re.compile(r"쿠팡|11번가|지마켓|g마켓|ssg|옥션|위메프|티몬|네이버|카카오|페이먼츠|결제|이니시스|kcp|토스|배달|요기요|우체국|인터넷|온라인|\.com")

    def out_of_jurisdiction(self):
        g = defaultdict(list)
        for e in self.exps:
            area = self.AREA.get(e["source_id"])
            if not area or e["amount"] <= 0:
                continue
            region = e.get("payee_region")  # 거래 행에 적힌 주소 (프랜차이즈 본사 주소가 아님)
            if not region or region in area or region == "서울" or (e["source_id"] == "seoul" and region.startswith("서울")):
                continue
            pname = (e.get("payee_raw") or "").lower()
            if self.ONLINE.search(pname) or is_platform(pname) or self.CHAIN.search(pname) or pname.rstrip(")").endswith("점") \
                    or e["category"] in ("물품·구매", "경조사", "성금·회비·격려금"):
                continue
            g[(e["subject_id"], e["date"][:4])].append((e, region))
        for (sid, y), items in g.items():
            regions = Counter(r for _, r in items)
            src = items[0][0]["source_id"]
            self.add(
                "OUT_OF_JURISDICTION", sid, src, [e for e, _ in items],
                observed={"transactionCount": len(items), "totalAmount": sum(e["amount"] for e, _ in items), "regions": dict(regions)},
                reference={"type": "REGULATORY", "value": ", ".join(sorted(self.AREA[src])),
                           "description": "회계관리 훈령 별표 2의2 — 관련 근무지와 무관한 지역 사용 제한(출장명령서 등 증빙 시 허용)"
                                          + (". 광역의회 범위는 훈령에 명시되지 않아 시·군·구 기준을 준용한 해석" if src == "seoul" else "")},
                explanation=f"{y}년 {self.subj_name(sid)}의 업무추진비 {len(items)}건이 {self.AREA_LABEL[src]} 밖({', '.join(list(regions)[:4])})에서 결제되었습니다. "
                            f"출장 등 직무 관련 증빙이 있으면 허용됩니다.",
                period={"start": f"{y}-01-01", "end": f"{y}-12-31", "label": f"{y}년"},
                funding_type=items[0][0]["funding_type"], metric=len(items),
            )

    # ------------------------------------------------------------------ B1
    def term_end_spike(self):
        excl = ("사무실_보증금", "정치_금융비용")
        base_s, base_e = date(2024, 1, 1), date(2024, 3, 31)
        win_s, win_e = date(2024, 4, 11), date(2024, 5, 29)
        stats = []
        for sid, rows in self.by_subject.items():
            s = self.subjects.get(sid)
            if not s or s["type"] != "LEGISLATOR" or "제21대" not in s["terms"]:
                continue
            rows = [e for e in rows if e["date"] and e["category"] not in excl and e["id"].startswith("ka21")]
            base = sum(e["amount"] for e in rows if base_s <= date.fromisoformat(e["date"]) <= base_e)
            win = [e for e in rows if win_s <= date.fromisoformat(e["date"]) <= win_e and e["amount"] > 0]
            wamt = sum(e["amount"] for e in rows if win_s <= date.fromisoformat(e["date"]) <= win_e)
            if base <= 0:
                continue
            ratio = (wamt / 49) / (base / 91)
            stats.append((sid, ratio, wamt, base, win, "제22대" in s["terms"]))
        if len(stats) < 50:
            return
        p90 = float(np.percentile([x[1] for x in stats], 90))
        for sid, ratio, wamt, base, win, reelected in stats:
            if ratio >= 2.5 and wamt >= 10_000_000 and ratio >= p90:
                cats = Counter()
                for e in win:
                    cats[e["category"]] += e["amount"]
                self.add(
                    "TERM_END_SPIKE", sid, "ka-money", win,
                    observed={"ratio": round(ratio, 2), "windowAmount": wamt, "baselineAmount": base, "reelected22": reelected,
                              "topCategories": [{"category": c, "amount": v} for c, v in cats.most_common(5)]},
                    reference={"type": "STATISTICAL", "description": f"제21대 의원 {len(stats)}명의 같은 비율 분포 90백분위수",
                               "value": round(p90, 2), "sampleSize": len(stats),
                               "window": "2024-04-11~05-29 (49일)", "baseline": "2024-01-01~03-31 (91일)"},
                    explanation=f"{self.subj_name(sid)}의 총선 이후~임기 종료 직전(49일) 하루 평균 지출이 1~3월의 {ratio:.1f}배입니다"
                                f"(해당 기간 {won(wamt)}). {'제22대에 재선되었습니다.' if reelected else '제22대 자료에는 없습니다(불출마·낙선 등).'} "
                                f"사무소 정리·의정보고서 발간 등 임기말의 정상 지출일 수 있습니다.",
                    period={"start": "2024-04-11", "end": "2024-05-29", "label": "제21대 임기 종료 직전"},
                    funding_type="POLITICAL_FUND", metric=ratio,
                )

    def election_year_change(self):
        """C2: 총선 직전(2024-01-01~04-10)의 월평균 지출을 전년도(2023) 월평균과 비교."""
        excl = ("사무실_보증금", "정치_금융비용")
        base_s, base_e, win_s, win_e = date(2023, 1, 1), date(2023, 12, 31), date(2024, 1, 1), date(2024, 4, 10)
        stats = []
        for sid, rows in self.by_subject.items():
            s = self.subjects.get(sid)
            if not s or s["type"] != "LEGISLATOR":
                continue
            if "제21대" not in s["terms"]:
                continue  # 2023년 한 해 전체를 현직으로 보낸 의원만 비교 (예비후보·승계 의원 제외)
            rows = [e for e in rows if e["date"] and e["category"] not in excl and e["id"].startswith(("ka23", "ka21"))]
            if min((e["date"] for e in rows if e["id"].startswith("ka23")), default="9999") > "2023-02-28":
                continue
            base = sum(e["amount"] for e in rows if base_s <= date.fromisoformat(e["date"]) <= base_e)
            win = [e for e in rows if win_s <= date.fromisoformat(e["date"]) <= win_e]
            wamt = sum(e["amount"] for e in win)
            if base <= 0 or not win:
                continue
            ratio = (wamt / ((win_e - win_s).days + 1)) / (base / 365)
            stats.append((sid, ratio, wamt, base, [e for e in win if e["amount"] > 0]))
        if len(stats) < 50:
            return
        p90 = float(np.percentile([x[1] for x in stats], 90))
        for sid, ratio, wamt, base, win in stats:
            if ratio >= 2.0 and ratio >= p90 and wamt - base * 101 / 365 >= 10_000_000:
                cats = Counter()
                for e in win:
                    cats[e["category"]] += e["amount"]
                camp = sum(e["amount"] for e in win if re.search(r"선거|예비후보", e.get("description") or ""))
                self.add(
                    "ELECTION_YEAR_CHANGE", sid, "ka-money", win,
                    observed={"ratio": round(ratio, 2), "windowAmount": wamt, "baselineAmount": base, "campaignWordAmount": camp,
                              "topCategories": [{"category": c, "amount": v} for c, v in cats.most_common(5)]},
                    reference={"type": "STATISTICAL", "description": f"2023·2024년 자료가 모두 있는 의원 {len(stats)}명의 같은 비율 분포 90백분위수",
                               "value": round(p90, 2), "sampleSize": len(stats),
                               "window": "2024-01-01~04-10 (총선 전 101일)", "baseline": "2023-01-01~12-31 (365일)"},
                    explanation=f"{self.subj_name(sid)}의 총선 전 101일(2024-01-01~04-10) 하루 평균 정치자금 지출이 2023년의 {ratio:.1f}배입니다"
                                f"(해당 기간 {won(wamt)}, 그중 내역에 '선거·예비후보'가 적힌 지출 {won(camp)}). "
                                f"예비후보자 활동 경비는 정치자금으로 쓸 수 있어 선거 직전 증가는 흔하며, 선거비용 자체는 이 자료에 없습니다.",
                    period={"start": "2024-01-01", "end": "2024-04-10", "label": "제22대 총선 직전"},
                    funding_type="POLITICAL_FUND", metric=ratio,
                )

    # 국회의원: 연도 × 대분류(오마이뉴스 분류의 앞부분)별 지출을 의원끼리 비교
    def category_outlier(self):
        per = defaultdict(lambda: defaultdict(list))  # (year, 대분류) -> sid -> rows
        for e in self.exps:
            if e["source_id"] != "ka-money" or not e["date"] or not e.get("category"):
                continue
            per[(e["date"][:4], e["category"].split("_")[0])][e["subject_id"]].append(e)
        for (y, cat), by_sid in per.items():
            totals = {sid: sum(e["amount"] for e in rows) for sid, rows in by_sid.items()}
            vals = [v for v in totals.values() if v > 0]
            if len(vals) < 50:
                continue
            med, p95 = float(np.median(vals)), float(np.percentile(vals, 95))
            for sid, amt in totals.items():
                if amt >= p95 and amt >= 3 * med and amt >= 10_000_000:
                    rows = [e for e in by_sid[sid] if e["amount"] > 0]
                    subs = Counter()
                    for e in rows:
                        subs[e["category"]] += e["amount"]
                    self.add(
                        "CATEGORY_SPEND_OUTLIER", sid, "ka-money", rows,
                        observed={"category": cat, "amount": amt, "ratioToMedian": round(amt / med, 1),
                                  "byCategory": dict(subs.most_common(5))},
                        reference={"type": "STATISTICAL", "description": f"{y}년 '{cat}' 지출이 있는 의원 {len(vals)}명의 분포",
                                   "value": round(p95), "median": None, "sampleSize": len(vals), "medianAmount": round(med)},
                        explanation=f"{y}년 {self.subj_name(sid)}의 '{cat}' 지출 {won(amt)}이 같은 항목 의원 중앙값({won(med)})의 {amt / med:.1f}배로, "
                                    f"비교 대상 {len(vals)}명 중 상위 5%입니다. 지역구 크기·사무소 수·활동 방식에 따라 클 수 있어, 무엇에 썼는지 거래를 확인해야 합니다.",
                        period={"start": f"{y}-01-01", "end": f"{y}-12-31", "label": f"{y}년"},
                        funding_type="POLITICAL_FUND", metric=amt / med, extra={"category": cat},
                    )

    # 지방의회: 같은 직책(의장/부의장/상임위원장)끼리 의회를 넘어 월평균 업무추진비를 비교
    ROLE_GROUP = (("의장", re.compile(r"^의장$")), ("부의장", re.compile(r"^(제\d)?부의장$")),
                  ("상임위원장", re.compile(r"위원장$")))

    def role_outlier(self):
        groups = defaultdict(list)
        for sid, rows in self.by_subject.items():
            s = self.subjects.get(sid)
            if not s or s["type"] != "COUNCIL_ROLE" or REGISTRY.get(s.get("org_source"), {}).get("level") != "기초":
                continue  # 광역의회(서울시의회)는 예산 규모가 달라 구의회와 같은 줄에 세우지 않는다
            label = next((g for g, rx in self.ROLE_GROUP if rx.search(s.get("role") or "")), None)
            if not label or "예산결산" in (s.get("role") or ""):
                continue
            by_year = defaultdict(list)
            for e in rows:
                if e["funding_type"] == "COUNCIL_OPERATION" and e["date"]:
                    by_year[e["date"][:4]].append(e)
            for y, ys in by_year.items():
                months = {e["date"][:7] for e in ys}
                if len(months) < 6:
                    continue
                groups[(label, y)].append((sid, sum(e["amount"] for e in ys) / len(months), len(months), ys))
        for (label, y), items in groups.items():
            vals = [x[1] for x in items if x[1] > 0]
            if len(vals) < 15:
                continue
            med, p95 = float(np.median(vals)), float(np.percentile(vals, 95))
            for sid, avg, nm, ys in items:
                if avg >= p95 and avg >= 2 * med:
                    self.add(
                        "ROLE_SPEND_OUTLIER", sid, ys[0]["source_id"], [e for e in ys if e["amount"] > 0],
                        observed={"role": label, "monthlyAverage": round(avg), "months": nm, "ratioToMedian": round(avg / med, 1),
                                  "totalAmount": sum(e["amount"] for e in ys)},
                        reference={"type": "STATISTICAL", "description": f"{y}년 서울 구의회 {label} {len(vals)}곳(직책·기수 단위)의 월평균 의회운영업무추진비",
                                   "value": round(p95), "sampleSize": len(vals), "medianAmount": round(med)},
                        explanation=f"{y}년 {self.subj_name(sid)}의 월평균 의회운영업무추진비 {won(avg)}이 서울 구의회 {label} 중앙값({won(med)})의 {avg / med:.1f}배입니다"
                                    f"(자료 {nm}개월). 의회마다 예산 규모(총액한도)가 달라 클 수 있으니 집행 내역을 함께 보세요.",
                        period={"start": f"{y}-01-01", "end": f"{y}-12-31", "label": f"{y}년"},
                        funding_type="COUNCIL_OPERATION", metric=avg / med, extra={"roleGroup": label},
                    )

    def month_spike(self):
        for sid, rows in self.by_subject.items():
            s = self.subjects.get(sid)
            if not s or s["type"] == "LEGISLATOR":
                continue
            months = defaultdict(list)
            for e in rows:
                months[e["date"][:7]].append(e)
            if len(months) < 6:
                continue
            totals = {m: sum(e["amount"] for e in v) for m, v in months.items()}
            med = float(np.median(list(totals.values())))
            if med <= 0:
                continue
            for m, amt in totals.items():
                if amt >= 3 * med and amt >= 1_000_000:
                    tags = []
                    if m.endswith("-12"):
                        tags.append("12월")
                    if s.get("term_end") and m == s["term_end"][:7]:
                        tags.append("임기 종료월")
                    self.add(
                        "MONTH_SPIKE", sid, rows[0]["source_id"], months[m],
                        observed={"month": m, "monthAmount": amt, "ratioToMedian": round(amt / med, 2), "tags": tags},
                        reference={"type": "STATISTICAL", "description": f"같은 주체의 월별 합계 중앙값 ({len(totals)}개월)",
                                   "value": round(med), "sampleSize": len(totals)},
                        explanation=f"{m} {self.subj_name(sid)}의 지출 {won(amt)}이 월 중앙값({won(med)})의 {amt / med:.1f}배입니다"
                                    + (f" ({', '.join(tags)})" if tags else "") + ". 정례회·명절·행사 등 일정과 대조가 필요합니다.",
                        period={"start": f"{m}-01", "end": period_range(m)[1], "label": m},
                        funding_type=rows[0]["funding_type"], metric=amt / med,
                    )

    # ------------------------------------------------------------------ B3
    EXPECTED_RECURRING = re.compile(r"임대료|관리비|보증금|숙소|신문|잡지|인건비|당비|의원모임|렌터카|통신|문자|금융|연감|차량_|교통_|후원_")
    EXPECTED_RECURRING_DESC = re.compile(r"렌탈|렌트|임대|임차|리스|정수기|복합기|복사기|비데|공기청정|세콤|캡스|에스원|보안|구독|요금|회비|자동이체|관리비|월세|"
                                         r"통신|인터넷|유지보수|호스팅|도메인|주차|청소|방역|소독|보험|정기|수수료|하이패스|구글|google|adobe|어도비|microsoft|"
                                         r"마이크로소프트|apple|애플|zoom|줌|notion|노션|chatgpt|openai|클라우드|대여|s1|에스원|축기|조기|근조|화환|화분|축하기")

    def recurring_same_amount(self):
        g = defaultdict(list)
        for e in self.exps:
            if e["amount"] < 20_000 or not e.get("merchant_id") or not e["date"]:
                continue
            if re.search(r"google|adobe|microsoft|apple|하이플러스|하이패스|은행|금고|농협", (e.get("payee_raw") or "").lower()):
                continue
            if self.EXPECTED_RECURRING.search(e["category"] or "") or self.EXPECTED_RECURRING_DESC.search(
                    f"{e.get('description') or ''} {e.get('payee_raw') or ''}".lower()):
                continue
            g[(e["subject_id"], e["merchant_id"], e["amount"])].append(e)
        per_subject = defaultdict(list)
        for (sid, mid, amt), items in g.items():
            months = {e["date"][:7] for e in items}
            if len(months) >= 4:
                per_subject[sid].append((mid, amt, items, len(months)))
        for sid, groups in per_subject.items():
            ev = [e for g_ in groups for e in g_[2]]
            detail = sorted(({"merchantId": mid, "merchantName": self.merchants[mid]["name"], "amount": amt, "months": nm,
                              "category": items[0]["category"], "count": len(items)} for mid, amt, items, nm in groups),
                            key=lambda x: -x["amount"] * x["count"])
            self.add(
                "RECURRING_SAME_AMOUNT", sid, ev[0]["source_id"], ev,
                observed={"patternCount": len(groups), "transactionCount": len(ev), "totalAmount": sum(e["amount"] for e in ev),
                          "patterns": detail[:30]},
                reference={"type": "EXACT_MATCH", "description": "같은 거래처·같은 금액이 서로 다른 4개월 이상 (원래 정기적인 분류 제외)"},
                explanation=f"{self.subj_name(sid)}의 지출에서 같은 거래처에 같은 금액을 4개월 이상 반복 지급한 패턴이 {len(groups)}개 있습니다"
                            f"(예: {detail[0]['merchantName']} {won(detail[0]['amount'])} × {detail[0]['months']}개월). 정기 계약이 있는지 확인이 필요합니다.",
                funding_type=ev[0]["funding_type"], review="INFO", metric=len(groups),
            )

    # ------------------------------------------------------------------ B4
    def duplicates(self):
        g = defaultdict(list)
        for e in self.all_exps:
            if e["payee_type"] in ("INDIVIDUAL", "SELF"):
                continue  # 개인 수령인은 가려져 있어 서로 다른 사람에게 같은 금액을 준 경우와 구분할 수 없다
            key = (e["subject_id"], e["date"], e.get("time"), e["amount"], e.get("payee_raw") or e.get("payee_display"),
                   e.get("description"))
            g[key].append(e)
        per_subject = defaultdict(list)
        for key, items in g.items():
            if len(items) < 2:
                continue
            if items[0]["source_id"] == "ka-money":
                rnos = [e.get("receipt_no") for e in items]
                kind = "DIFFERENT_RECEIPTS" if all(rnos) and len(set(rnos)) == len(rnos) else "POSSIBLE_DOUBLE_ENTRY"
            else:
                kind = "CROSS_DOCUMENT" if len({e["doc_id"] for e in items}) > 1 else "SAME_DOCUMENT"
            per_subject[items[0]["subject_id"]].append((kind, items))
        labels = {"DIFFERENT_RECEIPTS": "영수증 번호가 달라 실제 반복 거래일 가능성", "POSSIBLE_DOUBLE_ENTRY": "영수증 번호가 같거나 없어 중복 기재 의심",
                  "CROSS_DOCUMENT": "서로 다른 공개 파일에 같은 거래가 중복 수록", "SAME_DOCUMENT": "같은 공개 파일 안에서 중복 기재"}
        for sid, groups in per_subject.items():
            ev = [e for _, items in groups for e in items]
            kinds = Counter(k for k, _ in groups)
            excess = sum(e["amount"] for _, items in groups for e in items[1:])
            self.add(
                "DUPLICATE_ENTRY", sid, ev[0]["source_id"], ev,
                observed={"groupCount": len(groups), "transactionCount": len(ev), "excessAmount": excess,
                          "byKind": {labels[k]: v for k, v in kinds.items()},
                          "groups": [{"kind": labels[k], "ids": [e["id"] for e in items], "amount": items[0]["amount"],
                                      "date": items[0]["date"], "payee": items[0].get("payee_display")} for k, items in groups[:100]]},
                reference={"type": "EXACT_MATCH", "description": "일자·시간·금액·거래처·내역 완전 일치"},
                explanation=f"{self.subj_name(sid)}의 지출에서 일자·금액·거래처·내역이 모두 같은 거래 묶음이 {len(groups)}개 있습니다"
                            f"(중복분 합계 {won(excess)}). " + " / ".join(f"{labels[k]} {v}개" for k, v in kinds.items()) + ".",
                funding_type=ev[0]["funding_type"],
                review="DATA_QUALITY" if kinds.keys() <= {"CROSS_DOCUMENT", "SAME_DOCUMENT", "POSSIBLE_DOUBLE_ENTRY"} else "NEEDS_CONTEXT",
                metric=excess,
            )

    # ------------------------------------------------------------------ B5
    def reversals(self):
        pairs, unmatched = {}, defaultdict(list)
        pos_index = defaultdict(list)
        for e in self.exps:
            if e["amount"] > 0 and e["date"]:
                pos_index[(e["subject_id"], e.get("merchant_id") or e.get("payee_raw"), e["amount"])].append(e)
        used = set()
        for e in self.exps:
            if e["amount"] >= 0 or not e["date"]:
                continue
            d = date.fromisoformat(e["date"])
            settlement = self.SETTLEMENT.search(e.get("description") or "")
            cands = [p for p in pos_index.get((e["subject_id"], e.get("merchant_id") or e.get("payee_raw"), -e["amount"]), [])
                     if p["id"] not in used and -180 <= (date.fromisoformat(p["date"]) - d).days <= 7]
            if cands:
                best = min(cands, key=lambda p: abs((date.fromisoformat(p["date"]) - d).days))
                used.add(best["id"])
                pairs[e["id"]] = best["id"]
            elif not settlement and e["amount"] <= -10_000:
                unmatched[e["subject_id"]].append(e)
        for sid, items in unmatched.items():
            self.add(
                "UNMATCHED_REVERSAL", sid, items[0]["source_id"], items,
                observed={"transactionCount": len(items), "totalAmount": sum(e["amount"] for e in items)},
                reference={"type": "EXACT_MATCH", "description": "같은 주체·거래처·절대금액의 양수 거래 (반환일 기준 -180일~+7일)"},
                explanation=f"{self.subj_name(sid)}의 취소·반환(음수) {len(items)}건({won(sum(e['amount'] for e in items))})은 짝이 되는 원거래를 찾지 못했습니다. "
                            f"부분 환불·전년도 거래·거래처 표기 차이일 수 있습니다.",
                funding_type=items[0]["funding_type"], review="DATA_QUALITY", metric=len(items),
            )
        return pairs

    SETTLEMENT = re.compile(r"기탁금|보증금|공동|분담|이자|정산|지원금|이월|선거비용|보전|후원회|안분|반반|할인|캐시백|포인트|적립|"
                            r"선거통장|선거동장|통장|이체|잔액|감처리")

    CORRECTION = re.compile(r"착오|사적|개인\s*사용|개인용도|개인\s*부담|오사용|잘못|오결제|오류승인|부정사용")

    def self_correction(self, pairs):
        reverse_pairs = {v: k for k, v in pairs.items()}
        g = defaultdict(set)
        for e in self.exps:
            if e["source_id"] != "ka-money":
                continue
            if self.CORRECTION.search(e.get("description") or ""):
                g[e["subject_id"]].add(e["id"])
                for other in (pairs.get(e["id"]), reverse_pairs.get(e["id"])):
                    if other:
                        g[e["subject_id"]].add(other)
        for sid, ids in g.items():
            items = [self.by_id[i] for i in ids]
            neg = sum(e["amount"] for e in items if e["amount"] < 0)
            self.add(
                "SELF_CORRECTION_RECORD", sid, "ka-money", items,
                observed={"transactionCount": len(items), "refundedAmount": neg,
                          "examples": sorted({e["description"] for e in items if e.get("description")})[:8]},
                reference={"type": "KEYWORD", "description": "내역의 착오·사적 사용·개인 사용 등 정정 표현"},
                explanation=f"{self.subj_name(sid)}의 보고서에 착오·개인 사용 등을 정정한 기록이 {len(items)}건 있습니다"
                            + (f"(반환 {won(-neg)})" if neg else "") + ". 회계책임자가 스스로 바로잡은 기록으로, 정정 자체는 투명성에 도움이 됩니다.",
                funding_type="POLITICAL_FUND", review="INFO", metric=len(items),
            )

    # ------------------------------------------------------------------ C1 / C3
    SERVICE_CATS = ("정책_비용", "정치_여론조사및컨설팅", "홍보_비용등")
    VAGUE = re.compile(r"^(정책연구용역비?|정책용역비?|연구용역비?|용역비?|용역대금|용역비용|여론조사(비|비용|대금|용역)?|컨설팅(비|비용|료)?|자문(료|비)?|"
                       r"홍보비용?|홍보물|기타|대금|비용|수수료|지급|잔금|계약금|중도금|정책개발비|착오지출|현수막등|제작비|인쇄비)(\(.*\))?$")

    def service_rules(self):
        cats = defaultdict(list)
        for e in self.exps:
            if e["source_id"] == "ka-money" and e["category"] in self.SERVICE_CATS and e["amount"] > 0:
                cats[e["category"]].append(e)
        p95 = {c: float(np.percentile([e["amount"] for e in v], 95)) for c, v in cats.items() if len(v) >= 30}
        for c, rows in cats.items():
            if c not in p95:
                continue
            for e in rows:
                d = re.sub(r"\s+", "", e.get("description") or "")
                if e["amount"] >= max(p95[c], 3_000_000) and (len(d) <= 2 or self.VAGUE.match(d)):
                    self.add(
                        "LARGE_VAGUE_SERVICE", e["subject_id"], "ka-money", [e],
                        observed={"amount": e["amount"], "category": c, "description": e.get("description"), "payee": e.get("payee_display")},
                        reference={"type": "STATISTICAL", "description": f"'{c}' 분류 지출 95백분위수", "value": round(p95[c]), "sampleSize": len(rows)},
                        explanation=f"{self.subj_name(e['subject_id'])}이 {e['date']} '{e.get('payee_display')}'에 {won(e['amount'])}을 지출했으나 "
                                    f"내역이 '{e.get('description') or '(없음)'}'로만 적혀 있어 무엇에 대한 비용인지 알기 어렵습니다.",
                        funding_type="POLITICAL_FUND", metric=e["amount"],
                    )
        g = defaultdict(list)
        for rows in cats.values():
            for e in rows:
                if e.get("merchant_id"):
                    g[(e["subject_id"], e["merchant_id"])].append(e)
        for (sid, mid), items in g.items():
            total = sum(e["amount"] for e in items)
            pr_only = all(e["category"] == "홍보_비용등" for e in items)
            if (not pr_only and len(items) >= 2 and total >= 5_000_000) or (pr_only and len(items) >= 3 and total >= 30_000_000):
                self.add(
                    "REPEAT_SERVICE_VENDOR", sid, "ka-money", items,
                    observed={"transactionCount": len(items), "totalAmount": total, "merchantId": mid, "merchantName": self.merchants[mid]["name"],
                              "categories": dict(Counter(e["category"] for e in items))},
                    reference={"type": "EXACT_MATCH", "description": "정책·컨설팅·홍보 분류에서 같은 거래처 3회 이상 & 합계 1,000만원 이상"},
                    explanation=f"{self.subj_name(sid)}이 '{self.merchants[mid]['name']}'에 정책·컨설팅·홍보 명목으로 {len(items)}회, 총 {won(total)}을 지급했습니다. "
                                f"계약 내용과 결과물은 공개자료로 확인할 수 없습니다.",
                    funding_type="POLITICAL_FUND", review="INFO", metric=total, extra={"merchantId": mid},
                )

    def travel_same_day(self):
        g = defaultdict(list)
        for e in self.exps:
            if e["source_id"] != "ka-money" or e["amount"] <= 0 or not e["date"]:
                continue
            if e["category"] in ("교통_항공", "교통_철도등"):
                g[(e["subject_id"], e["date"], e["category"], e["amount"])].append(e)
            elif e["category"] == "차량_주유":
                g[(e["subject_id"], e["date"], e["category"], None)].append(e)
        per_subject = defaultdict(list)
        for (sid, d, c, amt), items in g.items():
            if (amt is not None and len(items) >= 2) or (amt is None and len(items) >= 3):
                per_subject[sid].append((d, c, items))
        for sid, groups in per_subject.items():
            ev = [e for _, _, items in groups for e in items]
            self.add(
                "TRAVEL_SAME_DAY_REPEAT", sid, "ka-money", ev,
                observed={"occurrences": len(groups), "transactionCount": len(ev), "byCategory": dict(Counter(c for _, c, _ in groups)),
                          "groups": [{"date": d, "category": c, "count": len(items), "total": sum(e["amount"] for e in items),
                                      "ids": [e["id"] for e in items]} for d, c, items in sorted(groups, key=lambda x: (x[0], x[1]))[:100]]},
                reference={"type": "EXACT_MATCH", "description": "같은 날 같은 금액 항공·철도 2건 이상 / 같은 날 주유 3회 이상"},
                explanation=f"{self.subj_name(sid)} 정치자금에서 같은 날 교통·주유 결제가 반복된 날이 {len(groups)}일 있습니다. 보좌진 동행·복수 차량 등 정상 사례가 많습니다.",
                funding_type="POLITICAL_FUND", review="INFO", metric=len(groups),
            )

    # ------------------------------------------------------------------ E1 / E2 / DQ
    def disclosure_gap(self, documents):
        for src, name in COUNCILS.items():
            mpath = RAW / src / "manifest.json"
            rpath = STAGING / f"{src}_parse_report.json"
            if not mpath.exists():
                continue
            manifest = json.loads(mpath.read_text())
            covered = set()
            for p in manifest:
                per = parse_period(p["post_title"]) or p.get("period")
                if not per:
                    continue
                s, e = period_range(per)
                d = date.fromisoformat(s)
                while d.isoformat() <= e:
                    covered.add(d.isoformat()[:7])
                    d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            if not covered:
                continue
            first, last = min(covered), max(covered)
            missing, d = [], date.fromisoformat(first + "-01")
            while d.isoformat()[:7] <= last:
                if d.isoformat()[:7] not in covered:
                    missing.append(d.isoformat()[:7])
                d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            report = json.loads(rpath.read_text()) if rpath.exists() else []
            if isinstance(report, dict):
                report = report.get("files", [])
            ocr_rep = STAGING / f"{src}_ocr_report.json"
            ocr_done = {f.get("file") for f in json.loads(ocr_rep.read_text()).get("files", []) if f.get("status") == "parsed"} if ocr_rep.exists() else set()
            problems = [r for r in report if (r.get("status") == "unparsed" and (r.get("filename") or r.get("file")) not in ocr_done)
                        or r.get("duplicate_of") or r.get("rejected_rows")]
            if not missing and not problems:
                continue
            self.add(
                "DISCLOSURE_GAP", f"org-{src}", src, [],
                observed={"firstMonth": first, "lastMonth": last, "missingMonths": missing,
                          "problemFiles": [{"period": r.get("period"), "filename": r.get("filename") or r.get("file"),
                                            "issue": r.get("reason") or ("날짜 오류로 제외된 행 있음" if r.get("rejected_rows") else None),
                                            "rejectedRows": n_rejected(r)} for r in problems][:50]},
                reference={"type": "DISCLOSURE", "description": "게시판 첫 공개 월~최근 월의 월별 공개 여부와 첨부 상태"},
                explanation=f"{name} 업무추진비 게시판({first}~{last})에서 공개 게시글이 없는 달이 {len(missing)}개, "
                            f"문제가 있는 첨부가 {len(problems)}건 있습니다. 훈령상 공개는 최소 분기 단위의 노력 의무이므로 위반을 뜻하지 않습니다.",
                period={"start": first + "-01", "end": period_range(last)[1], "label": f"{first}~{last}"},
                review="DATA_QUALITY", metric=len(missing) + len(problems),
            )

    def low_specificity(self):
        for sid, rows in self.by_subject.items():
            if len(rows) < 30:
                continue
            src = rows[0]["source_id"]
            descs = Counter(e.get("description") for e in rows)
            top_desc, top_n = descs.most_common(1)[0]
            share = top_n / len(rows)
            miss_att = sum(1 for e in rows if is_hospitality(e) and not e.get("attendees")) if src != "ka-money" else 0
            hosp = sum(1 for e in rows if is_hospitality(e))
            miss_payee = sum(1 for e in rows if e["payee_type"] == "MISSING")
            att_share = miss_att / hosp if hosp else 0
            reasons = []
            if share >= 0.8 and top_desc:
                reasons.append(f"집행목적의 {share:.0%}가 같은 문구('{top_desc}')")
            if src != "ka-money" and hosp >= 20 and att_share >= 0.2:
                reasons.append(f"식사·다과 지출의 {att_share:.0%}에 대상 인원수 없음")
            if miss_payee / len(rows) >= 0.2:
                reasons.append(f"{miss_payee / len(rows):.0%}에 사용처 없음")
            if not reasons:
                continue
            self.add(
                "LOW_SPECIFICITY", sid, src, [],
                observed={"transactionCount": len(rows), "topDescription": top_desc, "topDescriptionShare": round(share, 3),
                          "attendeesMissingShare": round(att_share, 3), "payeeMissingCount": miss_payee},
                reference={"type": "DISCLOSURE", "description": "훈령 공개 항목(사용자·일시·장소·집행목적·대상 인원수·금액·결제방법·비목)"},
                explanation=f"{self.subj_name(sid)}: " + ", ".join(reasons) + ". 집행 목적을 구체적으로 알기 어렵습니다. 공개 서식상 허용된 방식일 수 있습니다.",
                period={"start": min(e["date"] for e in rows if e["date"]), "end": max(e["date"] for e in rows if e["date"])},
                funding_type=rows[0]["funding_type"], review="DATA_QUALITY", metric=share,
            )

    def out_of_period(self):
        g = defaultdict(list)
        for e in self.exps:
            if "DATE_OUTSIDE_REPORT_PERIOD" in e["quality"]["flags"]:
                g[(e["doc_id"], e["subject_id"])].append(e)
        for (doc, sid), items in g.items():
            self.add(
                "OUT_OF_PERIOD_DATE", sid, items[0]["source_id"], items,
                observed={"transactionCount": len(items), "documentId": doc, "dates": sorted({e["date"] for e in items})[:20]},
                reference={"type": "DISCLOSURE", "description": "원본 문서의 공개 대상 기간"},
                explanation=f"{self.subj_name(sid)}의 {len(items)}건이 해당 공개 문서의 대상 기간 밖 날짜로 적혀 있습니다. 늦은 정산·오기·OCR 오류일 수 있습니다.",
                funding_type=items[0]["funding_type"], review="DATA_QUALITY", metric=len(items),
            )

    def data_quality(self, source_id, ev):
        """자료 성격은 근거 거래가 실린 문서 형식으로 정한다. 근거 거래가 없으면 그 기관의 문서 전체로 본다."""
        if source_id == "ka-money":
            return "OCR_SECONDARY"
        rows = [self.by_id[i] for i in ev if i in self.by_id]
        if any(r["quality"].get("ocr") for r in rows):
            return "OCR_SCAN"
        fmts = ({self.doc_format.get(r["doc_id"]) for r in rows} if rows
                else {f for d, f in self.doc_format.items() if d.startswith(source_id + ":")})
        fmts.discard(None)
        if fmts == {"PDF"}:
            return "PDF_TEXT"
        if fmts == {"XLSX"}:
            return "STRUCTURED_SOURCE"
        return "MIXED_SOURCE"

    def run(self, documents):
        self.doc_format = {d["doc_id"]: ("PDF" if (d.get("format") or "").upper().startswith("PDF") else "XLSX") for d in documents}
        steps = [self.meal_over_standard, self.ka_high_meal, self.repeated_merchant, self.merchant_concentration,
                 self.restricted_hours_days, self.ka_weekend_share, self.same_day_split, self.restricted_sector,
                 self.private_expense_keyword, self.purpose_mismatch, self.cash_payment, self.out_of_jurisdiction,
                 self.term_end_spike, self.election_year_change, self.category_outlier, self.role_outlier, self.month_spike, self.recurring_same_amount, self.duplicates]
        for step in steps:
            step()
        pairs = self.reversals()
        self.self_correction(pairs)
        self.service_rules()
        self.travel_same_day()
        self.disclosure_gap(documents)
        self.low_specificity()
        self.out_of_period()
        return pairs


def main():
    exps = read_jsonl(NORMALIZED / "expenditures.jsonl")
    subjects = json.loads((NORMALIZED / "subjects.json").read_text())
    merchants = json.loads((NORMALIZED / "merchants.json").read_text())
    documents = json.loads((NORMALIZED / "documents.json").read_text())
    det = Detector(exps, subjects, merchants)
    pairs = det.run(documents)
    write_json(NORMALIZED / "findings.json", det.findings)
    write_json(NORMALIZED / "reversal_pairs.json", pairs)
    c = Counter(f["ruleId"] for f in det.findings)
    for r, n in sorted(c.items(), key=lambda x: -x[1]):
        print(f"{n:6d}  {r}", file=sys.stderr)
    print(f"{len(det.findings)} findings, {len(pairs)} reversal pairs", file=sys.stderr)


if __name__ == "__main__":
    main()
