from collections import defaultdict
from calendar import monthrange
import json
from statistics import median

from .db import escaped_like, payload, records
from .repository import NotFound, Repository


class Dashboard(Repository):
    def meta(self):
        parties = [
            r[0]
            for r in self.db.execute(
                "SELECT DISTINCT party FROM subjects WHERE type='LEGISLATOR' AND party IS NOT NULL ORDER BY party"
            )
        ]
        return {
            "serviceName": "나랏일보고서",
            "pseudonyms": self.config.pseudonyms,
            "indexedAt": payload(self.db, "indexed_at"),
            "counts": payload(self.db, "counts", {}),
            "fundingTypes": payload(self.db, "funding", {}),
            "councils": list(payload(self.db, "registry", {}).values()),
            "parties": parties,
            "reports": [
                {
                    "id": d,
                    "title": self.document(d)["title"],
                    "period": self.document(d)["period"],
                }
                for d in ["ka:2024-22", "ka:2024-21", "ka:2023"]
                if self.document(d)
            ],
            "documents": self.db.execute("SELECT COUNT(*) FROM documents").fetchone()[
                0
            ],
            "merchants": self.db.execute("SELECT COUNT(*) FROM merchants").fetchone()[
                0
            ],
            "naverMapsClientId": self.config.naver_client_id,
            "locationPrecision": "시·군·구",
            "assembly": payload(self.db, "assembly_summary"),
        }

    def councils(self, scope):
        where, args = self.where(scope, "t.source!='ka-money'")
        rows = records(
            self.db,
            f"""SELECT t.source id,SUM(t.amount) amount,COUNT(*) count,
           COUNT(DISTINCT t.month) months,MIN(t.date) "firstDate",MAX(t.date) "lastDate"
           FROM transactions t WHERE {where} GROUP BY t.source ORDER BY amount DESC""",
            args,
        )
        registry = payload(self.db, "registry", {})
        for row in rows:
            row.update(
                {
                    k: registry.get(row["id"], {}).get(k)
                    for k in ["name", "region", "level", "board"]
                }
            )
            row["monthlyAverage"] = (
                row["amount"] / row["months"] if row["months"] else None
            )
        return {"scope": scope, "rows": rows}

    def council(self, cid, scope):
        registry = payload(self.db, "registry", {})
        if cid not in registry:
            raise NotFound("의회를 찾을 수 없습니다.")
        agg = self.aggregates(scope, "t.source=?", [cid])
        where, args = self.where(scope, "t.source=?", [cid])
        roles = records(
            self.db,
            f"""SELECT t.subject_id id,SUM(t.amount) amount,COUNT(*) count,
            COUNT(DISTINCT t.month) months,MIN(t.date) "firstDate",MAX(t.date) "lastDate"
            FROM transactions t WHERE {where} GROUP BY t.subject_id ORDER BY amount DESC""",
            args,
        )
        for role in roles:
            role["subject"] = self.subject(role["id"])
            role["subject"]["holders"] = [
                h
                for h in role["subject"]["holders"]
                if h["start"]
                and h["end"]
                and h["start"] <= scope["end"]
                and h["end"] >= scope["start"]
            ]
        return {
            "council": registry[cid],
            "scope": scope,
            **agg,
            "roles": roles,
            "transactions": self._council_transactions(cid, scope),
        }

    def _council_transactions(self, cid, scope):
        where, args = self.where(scope, "t.source=?", [cid])
        rows = records(
            self.db,
            f"SELECT t.* FROM transactions t WHERE {where} ORDER BY t.date DESC,t.id LIMIT 8",
            args,
        )
        return [self.transaction_row(r) for r in rows]

    def rankings(self, scope, target="members", metric="amount", party="", category=""):
        if target == "assets":
            people = payload(self.db, "asset_people", [])
            if party:
                people = [p for p in people if p.get("party") == party]
            field = "change" if metric == "change" else "cur"
            rows = [
                {
                    "id": p.get("sid"),
                    "name": self.person_name(p["name"]),
                    "party": p.get("party"),
                    "district": p.get("district"),
                    "amount": p["total"][field],
                    "value": p["total"][field],
                    "page": p["page"],
                }
                for p in people
            ]
            rows.sort(key=lambda r: (-r["value"], r["name"]))
            asset_source = payload(self.db, "asset_source", {})
            scope = {
                "kind": "as_of",
                "label": asset_source.get("basis", "") + " 신고재산",
                "start": asset_source.get("basis"),
                "end": asset_source.get("basis"),
                "unit": "KRW",
                "note": "신고가액 기준이며 시세·개인 소득과 다릅니다.",
            }
            chart = []
        elif target == "councils":
            rows = [
                r
                for r in self.councils(scope)["rows"]
                if r["level"] == "기초" and r["months"] >= 6
            ]
            for r in rows:
                r["value"] = (
                    r["monthlyAverage"] if metric == "monthly_average" else r["amount"]
                )
            rows.sort(key=lambda r: (-r["value"], r["id"]))
            chart = []
        else:
            rows, _, _ = self.member_rows(scope, party=party, category=category)
            for r in rows:
                r["value"] = r["amount"]
            chart = self.members(scope, party=party)["categories"]
        values = [r["value"] for r in rows]
        med = median(values) if values else None
        top = [
            {
                **r,
                "rank": i + 1,
                "ratioToMedian": r["value"] / med if med and med > 0 else None,
            }
            for i, r in enumerate(rows[:10])
        ]
        result = {
            "scope": scope,
            "target": target,
            "metric": metric,
            "rows": top,
            "n": len(rows),
            "median": med,
            "total": sum(values) if values else None,
            "mean": sum(values) / len(values) if values else None,
            "categories": chart,
        }
        if target == "members":
            result["monthly"] = self.members(scope, party=party)["monthly"]
        if target == "councils":
            result["note"] = (
                "기초의회 중 공개 6개월 이상만 비교합니다. 월평균의 분모는 각 행의 공개 개월입니다."
            )
        return result

    def _place_rows(self, scope, q=""):
        extra, values = "t.is_meal=1", []
        if q:
            name_column = "m.display_name" if self.config.pseudonyms else "m.name"
            extra += f" AND ({name_column} LIKE ? ESCAPE '\\' OR m.region LIKE ? ESCAPE '\\')"
            values.extend([escaped_like(q), escaped_like(q)])
        where, args = self.where(scope, extra, values)
        return records(
            self.db,
            f"""WITH f AS (
            SELECT t.* FROM transactions t JOIN merchants m ON m.id=t.merchant_id WHERE {where}
          ), totals AS (
            SELECT merchant_id,SUM(amount) amount,COUNT(*) count,SUM(retained_payment) payments,
              SUM(CASE WHEN amount<0 THEN 1 ELSE 0 END) refunds FROM f GROUP BY merchant_id
          ), positive_payers AS (
            SELECT merchant_id,COUNT(*) "payerCount" FROM (
              SELECT merchant_id,subject_id FROM f GROUP BY merchant_id,subject_id HAVING SUM(amount)>0
            ) GROUP BY merchant_id
          ) SELECT m.id,m.name,m.display_name,m.region,m.confidence,a.amount,a.count,a.payments,a.refunds,p."payerCount"
          FROM totals a JOIN merchants m ON m.id=a.merchant_id JOIN positive_payers p ON p.merchant_id=m.id
          WHERE a.amount>0 AND a.payments>0 ORDER BY a.payments DESC,a.amount DESC,m.id""",
            args,
        )

    def places(self, scope, region="", q="", sort="payments", page=1, page_size=12):
        all_rows = self._place_rows(scope, q)
        clusters = defaultdict(lambda: {"venues": 0, "payments": 0, "amount": 0})
        for r in all_rows:
            if r["region"]:
                cluster = clusters[r["region"]]
                cluster["venues"] += 1
                cluster["payments"] += r["payments"]
                cluster["amount"] += r["amount"]
        rows = [
            r
            for r in all_rows
            if not region
            or r["region"] == region
            or r["region"]
            and r["region"].startswith(region + " ")
        ]
        sort_key = {"payments": "payments", "amount": "amount", "payers": "payerCount"}[
            sort
        ]
        rows.sort(key=lambda r: (-r[sort_key], r["id"]))
        selected = rows[(page - 1) * page_size : page * page_size]
        for r in selected:
            r["name"] = self.name(r)
            r.pop("display_name", None)
        return {
            "scope": scope,
            "rows": selected,
            "total": len(rows),
            "page": page,
            "pageSize": page_size,
            "summary": {
                "amount": sum(r["amount"] for r in rows) if rows else None,
                "payments": sum(r["payments"] for r in rows),
            },
            "clusters": [{"region": k, **v} for k, v in clusters.items()],
            "locationPrecision": "시·군·구",
        }

    def place(self, mid, scope, page=1):
        merchant = self.db.execute(
            "SELECT * FROM merchants WHERE id=?", (mid,)
        ).fetchone()
        if not merchant:
            raise NotFound("거래처를 찾을 수 없습니다.")
        where, args = self.where(scope, "t.merchant_id=? AND t.is_meal=1", [mid])
        agg = self.aggregates(scope, "t.merchant_id=? AND t.is_meal=1", [mid])
        payers = records(
            self.db,
            f"""SELECT t.subject_id id,SUM(t.amount) amount,SUM(t.retained_payment) payments
            FROM transactions t WHERE {where} GROUP BY t.subject_id HAVING SUM(t.amount)>0
            ORDER BY payments DESC,amount DESC""",
            args,
        )
        for row in payers:
            row["subject"] = self.subject(row["id"])
        refund_count = self.db.execute(
            f"SELECT COUNT(*) FROM transactions t WHERE {where} AND t.amount<0", args
        ).fetchone()[0]
        return {
            "merchant": {
                "id": mid,
                "name": self.name(merchant),
                "region": merchant["region"],
                "aliases": json.loads(
                    merchant["display_aliases"]
                    if self.config.pseudonyms
                    else merchant["aliases"]
                ),
                "confidence": merchant["confidence"],
                "businessNumber": merchant["business_number"],
                "kind": merchant["kind"],
            },
            "scope": scope,
            **agg,
            "payerCount": len(payers),
            "payers": payers,
            "refunds": refund_count,
            "transactions": self.transactions(
                scope, merchant_id=mid, page=page, meal_only=True
            ),
            "locationPrecision": "시·군·구",
        }

    def overview(self, region, report_scope, council_scope):
        registry = payload(self.db, "registry", {})
        council = next(
            (cid for cid, value in registry.items() if value["region"] == region), None
        )
        members = self.members(report_scope, region=region, page_size=100)
        council_data = self.council(council, council_scope) if council else None
        return {
            "region": region,
            "scope": report_scope,
            "members": members,
            "council": council_data,
            "cityCouncil": self.council("seoul", council_scope)
            if region.startswith("서울")
            else None,
            "localFiscalAvailable": False,
        }

    def fiscal(self, year=2024, basis="actual"):
        fiscal = payload(self.db, "fiscal", {})
        years = fiscal.get("actuals", {}).get("years", {})
        if basis == "actual":
            values = years.get(str(year))
            if not values:
                raise NotFound("해당 연도의 결산 수집본이 없습니다.")
            through = values["through_month"]
            scope = {
                "kind": "annual" if through == 12 else "range",
                "label": f"{year}년 연간 결산"
                if through == 12
                else f"{year}년 {through}월까지 누계",
                "start": f"{year}-01-01",
                "end": f"{year}-{through:02d}-{monthrange(year, through)[1]:02d}",
                "unit": "KRW",
                "basis": "결산",
                "note": "국가채무는 해당 연도 말의 잔액으로 별도 표시합니다.",
            }
        else:
            values = None
            scope = {
                "kind": "budget",
                "label": f"{year}년 "
                + ("확정 예산" if basis == "budget" else "예산안"),
                "start": f"{year}-01-01",
                "end": f"{year}-12-31",
                "unit": "KRW",
                "basis": basis,
                "note": "결산 실적과 비교 기준이 다릅니다. 수집되지 않은 합계는 계산하지 않습니다.",
            }

        def section(name):
            container = fiscal.get(name, {})
            if name == "expenditure_by_ministry":
                if basis == "proposal":
                    item = (
                        container.get("proposal")
                        if str(container.get("proposal", {}).get("year")) == str(year)
                        else None
                    )
                elif basis == "budget":
                    item = (
                        container if str(container.get("year")) == str(year) else None
                    )
                else:
                    item = container.get("history", {}).get(str(year))
                return item
            item = container.get("years", {}).get(str(year))
            if not item:
                return None
            if isinstance(item, list):
                return (
                    {"basis": container.get("basis"), "items": item}
                    if basis == "budget" and "예산" in container.get("basis", "")
                    else None
                )
            label = item.get("basis", "")
            matches = (
                ("결산" in label)
                if basis == "actual"
                else (
                    "예산안" in label
                    if basis == "proposal"
                    else ("예산" in label and "예산안" not in label)
                )
            )
            return item if matches else None

        ministry = section("expenditure_by_ministry")
        sector = section("expenditure_by_sector")
        if basis != "actual" and not ministry and not sector:
            raise NotFound("해당 연도·기준의 예산 자료가 없습니다.")
        return {
            "scope": scope,
            "values": values,
            "source": fiscal.get("source"),
            "sectors": sector,
            "ministries": ministry,
            "revenue": section("revenue"),
            "taxes": section("national_tax_by_item"),
            "debt": fiscal.get("debt", {}).get("years", {}).get(str(year))
            if basis == "actual"
            else None,
            "history": [
                {"year": y, **v}
                for y, v in sorted(years.items())
                if v.get("through_month") == 12
            ],
            "actualYears": sorted((int(y) for y in years), reverse=True),
        }

    def sources(self):
        counts = payload(self.db, "counts", {})
        rules = payload(self.db, "rules", [])
        registry = payload(self.db, "registry", {})
        docs = records(
            self.db, "SELECT source,COUNT(*) count FROM documents GROUP BY source"
        )
        doc_counts = {r["source"]: r["count"] for r in docs}
        source_counts = records(
            self.db,
            'SELECT source,COUNT(*) count,MIN(date) "firstDate",MAX(date) "lastDate" FROM transactions WHERE duplicate_of IS NULL AND valid_period=1 GROUP BY source',
        )
        for row in source_counts:
            row["name"] = registry.get(row["source"], {}).get(
                "name", "국회의원 정치자금"
            )
            row["documents"] = doc_counts.get(row["source"], 0)
        fields = {}
        for fund, count in counts.items():
            values = self.db.execute(
                """SELECT SUM(CASE WHEN time IS NOT NULL THEN 1 ELSE 0 END) time_count,SUM(CASE WHEN attendees IS NOT NULL THEN 1 ELSE 0 END) attendees_count,SUM(CASE WHEN payment IS NOT NULL THEN 1 ELSE 0 END) payment_count
               FROM transactions WHERE duplicate_of IS NULL AND funding_type=?""",
                (fund,),
            ).fetchone()
            fields[fund] = {
                "count": count,
                "time": values[0],
                "attendees": values[1],
                "payment": values[2],
            }
        return {
            "indexedAt": payload(self.db, "indexed_at"),
            "counts": counts,
            "sources": source_counts,
            "rules": rules,
            "fields": fields,
            "findingCount": self.db.execute("SELECT COUNT(*) FROM findings").fetchone()[
                0
            ],
            "assetSource": payload(self.db, "asset_source"),
            "assembly": payload(self.db, "assembly_summary"),
            "geoSources": payload(self.db, "geo", {})
            .get("projection", {})
            .get("sources", []),
        }
