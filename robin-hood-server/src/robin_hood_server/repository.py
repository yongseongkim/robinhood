import json
from statistics import median

from .db import array_values, escaped_like, is_postgres, payload, records
from .index import public_merchant_id
from .scopes import REPORTS, month_series


class NotFound(LookupError):
    pass


class Repository:
    def __init__(self, db, config):
        self.db, self.config = db, config
        self.aliases = payload(db, "people_aliases", {}) if config.pseudonyms else {}

    def name(self, row):
        return row["display_name"] if self.config.pseudonyms else row["name"]

    def person_name(self, name):
        return self.aliases.get(name, name)

    def where(self, scope, extra="", values=()):
        sql = "t.duplicate_of IS NULL AND t.valid_period=1 AND t.funding_type=? AND t.date>=? AND t.date<=?"
        args = [scope["fundingType"], scope["start"], scope["end"]]
        if scope.get("reportId"):
            sql += " AND t.doc_id=?"
            args.append(scope["reportId"])
        if extra:
            sql += " AND " + extra
            args.extend(values)
        return sql, args

    def aggregates(self, scope, extra="", values=()):
        where, args = self.where(scope, extra, values)
        row = dict(
            self.db.execute(
                f"""SELECT SUM(t.amount) amount,COUNT(*) count,
          COALESCE(SUM(t.retained_payment),0) payments,COUNT(DISTINCT t.month) months,
          MIN(t.date) "firstDate",MAX(t.date) "lastDate" FROM transactions t WHERE {where}""",
                args,
            ).fetchone()
        )
        row["monthlyAverage"] = row["amount"] / row["months"] if row["months"] else None
        monthly = records(
            self.db,
            f"""SELECT t.month,SUM(t.amount) amount,COUNT(*) count,
          SUM(t.retained_payment) payments FROM transactions t WHERE {where} GROUP BY t.month ORDER BY t.month""",
            args,
        )
        categories = records(
            self.db,
            f"""SELECT t.category_group name,SUM(t.amount) amount,COUNT(*) count
          FROM transactions t WHERE {where} GROUP BY t.category_group ORDER BY amount DESC""",
            args,
        )
        return {
            "summary": row,
            "monthly": month_series(scope["start"], scope["end"], monthly),
            "categories": categories,
        }

    def subject(self, sid, report=None):
        row = self.db.execute("SELECT * FROM subjects WHERE id=?", (sid,)).fetchone()
        if not row:
            raise NotFound("지출 주체를 찾을 수 없습니다.")
        raw = json.loads(row["details"])
        term = (raw.get("terms") or {}).get(
            REPORTS.get(report, (None, "제22대"))[1], {}
        )
        holders = []
        for holder in raw.get("holders") or []:
            holders.append(
                {
                    "name": self.person_name(holder.get("name")),
                    "party": holder.get("party"),
                    "start": holder.get("period_start"),
                    "end": holder.get("period_end"),
                    "sourceUrl": holder.get("source_url"),
                    "sourceTitle": holder.get("source_title"),
                    "confidence": holder.get("confidence"),
                }
            )
        reports = [
            r[0]
            for r in self.db.execute(
                "SELECT DISTINCT doc_id FROM transactions WHERE subject_id=? AND funding_type='POLITICAL_FUND' ORDER BY doc_id DESC",
                (sid,),
            )
        ]
        role = (
            "의원"
            if self.config.pseudonyms and row["type"] == "COUNCIL_MEMBER"
            else row["role"]
        )
        return {
            "id": row["id"],
            "name": self.name(row),
            "type": row["type"],
            "source": row["source"],
            "reports": reports,
            "org": row["org"],
            "role": role,
            "term": row["term"],
            "party": term.get("party", row["party"]),
            "district": term.get("district", row["district"]),
            "attribution": raw.get("attribution_note"),
            "holders": holders,
        }

    def member_rows(self, scope, party="", q="", region="", category=""):
        term = REPORTS[scope["reportId"]][1]
        path = '$.terms."' + term + '"'
        extra = "s.type='LEGISLATOR' AND json_type(s.details,?)='object'"
        values = [path]
        party_expr = f"json_extract(s.details, '$.terms.\"{term}\".party')"
        district_expr = f"json_extract(s.details, '$.terms.\"{term}\".district')"
        if is_postgres(self.db):
            extra = (
                "s.type='LEGISLATOR' AND jsonb_typeof(s.details->'terms'->?)='object'"
            )
            values = [term]
            party_expr = f"s.details->'terms'->'{term}'->>'party'"
            district_expr = f"s.details->'terms'->'{term}'->>'district'"
        if party:
            extra += f" AND {party_expr}=?"
            values.append(party)
        if q:
            name_column = "s.display_name" if self.config.pseudonyms else "s.name"
            extra += f" AND ({name_column} LIKE ? ESCAPE '\\' OR {district_expr} LIKE ? ESCAPE '\\')"
            values.extend([escaped_like(q), escaped_like(q)])
        if region:
            parts = region.split()
            for part in parts:
                if part == "전남광주":
                    # Current administrative boundaries include the merger;
                    # historical reports retain their original district names.
                    extra += f" AND ({district_expr} LIKE ? ESCAPE '\\' OR {district_expr} LIKE ? ESCAPE '\\')"
                    values.extend([escaped_like("전남"), escaped_like("광주")])
                else:
                    extra += f" AND {district_expr} LIKE ? ESCAPE '\\'"
                    values.append(escaped_like(part))
        if category:
            extra += " AND t.category_group=?"
            values.append(category)
        where, args = self.where(scope, extra, values)
        rows = records(
            self.db,
            f"""SELECT s.id,s.name,s.display_name,{party_expr} party,{district_expr} district,
          SUM(t.amount) amount,COUNT(*) count FROM transactions t JOIN subjects s ON s.id=t.subject_id
          WHERE {where} GROUP BY s.id HAVING SUM(t.amount)>0 ORDER BY amount DESC,s.id""",
            args,
        )
        for r in rows:
            r["name"] = self.name(r)
            del r["display_name"]
        return rows, extra, values

    def members(
        self, scope, party="", q="", region="", page=1, page_size=12, sort="name"
    ):
        rows, extra, values = self.member_rows(scope, party, q, region)
        all_values = [r["amount"] for r in rows]
        if sort == "name":
            rows.sort(key=lambda r: (r["name"], r["id"]))
        ids = [r["id"] for r in rows]
        selected = f"t.subject_id IN (SELECT value FROM {array_values(self.db, '?')})"
        filters, args = selected, [json.dumps(ids)]
        agg = self.aggregates(scope, filters, args)
        return {
            **agg,
            "scope": scope,
            "total": len(rows),
            "page": page,
            "pageSize": page_size,
            "median": median(all_values) if all_values else None,
            "rows": rows[(page - 1) * page_size : page * page_size],
        }

    def profile(self, sid, scope, page=1):
        subject = self.subject(sid, scope.get("reportId"))
        row = self.db.execute(
            "SELECT details FROM subjects WHERE id=?", (sid,)
        ).fetchone()
        raw = json.loads(row[0])
        extras = self.db.execute(
            "SELECT * FROM extras WHERE subject_id=?", (sid,)
        ).fetchone()
        asset = json.loads(extras["assets"]) if extras and extras["assets"] else None
        activity = (
            json.loads(extras["activity"]) if extras and extras["activity"] else None
        )
        if asset:
            asset = {
                k: v
                for k, v in asset.items()
                if k not in ("name", "sid", "position", "party", "district")
            }
            asset["source"] = payload(self.db, "asset_source")
        if activity:
            m = activity.get("member") or {}
            activity = {
                "committees": m.get("CMITS"),
                "reelection": m.get("REELE_GBN_NM"),
                "bills": activity.get("bills") or {},
                "votes": activity.get("votes") or {},
                "fetchedAt": (payload(self.db, "assembly_summary", {}) or {}).get(
                    "fetched_at"
                ),
            }
        income_year = scope["start"][:4]
        income = raw.get("income", {}).get(income_year, {})
        return {
            "subject": subject,
            "scope": scope,
            **self.aggregates(scope, "t.subject_id=?", [sid]),
            "income": [
                {"name": k, "amount": v}
                for k, v in income.items()
                if "중복 가능" not in k
            ],
            "incomeCarry": {k: v for k, v in income.items() if "중복 가능" in k},
            "incomeYear": income_year,
            "assets": asset,
            "activity": activity,
            "transactions": self.transactions(scope, subject_id=sid, page=page),
            "findings": self.findings(
                subject_id=sid, funding=scope["fundingType"], limit=10
            ),
        }

    def transaction(self, tid):
        row = self.db.execute(
            "SELECT * FROM transactions WHERE id=?", (tid,)
        ).fetchone()
        if not row:
            raise NotFound("거래를 찾을 수 없습니다.")
        data = self.transaction_row(dict(row))
        data["scope"] = {
            "kind": "transaction",
            "label": "거래 1건",
            "start": row["date"],
            "end": row["date"],
            "fundingType": row["funding_type"],
            "unit": "KRW",
            "note": "공개자료의 수록 월과 거래 1건의 금액을 구분합니다.",
        }
        data["subject"] = self.subject(
            row["subject_id"], row["doc_id"] if row["doc_id"] in REPORTS else None
        )
        data["document"] = self.document(row["doc_id"])
        data["pair"] = (
            self.transaction_row(
                dict(
                    self.db.execute(
                        "SELECT * FROM transactions WHERE id=?", (row["pair"],)
                    ).fetchone()
                )
            )
            if row["pair"]
            and self.db.execute(
                "SELECT 1 FROM transactions WHERE id=?", (row["pair"],)
            ).fetchone()
            else None
        )
        data["findings"] = self.findings(
            subject_id=row["subject_id"],
            funding=row["funding_type"],
            evidence_id=tid,
            limit=1000,
        )
        return data

    def transaction_row(self, row):
        subject = self.subject(
            row["subject_id"], row["doc_id"] if row["doc_id"] in REPORTS else None
        )
        merchant = (
            self.db.execute(
                "SELECT * FROM merchants WHERE id=?", (row["merchant_id"],)
            ).fetchone()
            if row["merchant_id"]
            else None
        )
        payee = self.name(merchant) if merchant else row["payee"]
        if self.config.pseudonyms and row["payee_type"] == "INDIVIDUAL":
            payee = "개인(비공개)"
        description = row.get("description")
        if self.config.pseudonyms and description:
            source_name = self.db.execute(
                "SELECT name FROM subjects WHERE id=?", (row["subject_id"],)
            ).fetchone()[0]
            if len(source_name) >= 3:
                description = description.replace(source_name, subject["name"])
            if merchant:
                description = description.replace(merchant["name"], payee)
        return {
            "id": row["id"],
            "date": row["date"],
            "time": row["time"],
            "amount": row["amount"],
            "description": description,
            "category": row["category"],
            "subjectId": row["subject_id"],
            "subjectName": subject["name"],
            "merchantId": row["merchant_id"],
            "payee": payee,
            "fundingType": row["funding_type"],
            "account": row["account"],
            "attendees": row["attendees"],
            "payment": row["payment"],
            "budgetItem": row["budget_item"],
            "docId": row["doc_id"],
            "receiptNo": row.get("receipt_no"),
            "categorySource": row.get("category_source"),
            "rowRef": row["row_ref"],
            "flags": json.loads(row["flags"]),
            "quality": json.loads(row["quality"]),
            "duplicateOf": row["duplicate_of"],
            "pairId": row["pair"],
            "weekday": row["weekday"],
            "holiday": row["holiday"],
            "perPerson": row["amount"] / row["attendees"]
            if row["attendees"]
            and row["attendees"] > 0
            and row["amount"] > 0
            and row["funding_type"] != "POLITICAL_FUND"
            else None,
        }

    def transactions(
        self,
        scope,
        subject_id="",
        merchant_id="",
        category="",
        q="",
        page=1,
        page_size=12,
        meal_only=False,
    ):
        extra, values = [], []
        for column, value in [
            ("subject_id", subject_id),
            ("merchant_id", merchant_id),
            ("category_group", category),
        ]:
            if value:
                extra.append(f"t.{column}=?")
                values.append(value)
        if q:
            extra.append("t.description LIKE ? ESCAPE '\\'")
            values.append(escaped_like(q))
        if meal_only:
            extra.append("t.is_meal=1")
        where, args = self.where(scope, " AND ".join(extra), values)
        total = self.db.execute(
            f"SELECT COUNT(*) FROM transactions t WHERE {where}", args
        ).fetchone()[0]
        rows = records(
            self.db,
            f"SELECT t.* FROM transactions t WHERE {where} ORDER BY t.date DESC,t.id LIMIT ? OFFSET ?",
            [*args, page_size, (page - 1) * page_size],
        )
        return {
            "scope": scope,
            "total": total,
            "page": page,
            "pageSize": page_size,
            "rows": [self.transaction_row(r) for r in rows],
        }

    def document(self, doc_id):
        row = self.db.execute(
            "SELECT data FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def finding_filter(self, subject_id="", funding="", q="", evidence_id=""):
        conditions, args = ["1=1"], []
        if subject_id:
            conditions.append("subject_id=?")
            args.append(subject_id)
        if funding:
            conditions.append("funding_type=?")
            args.append(funding)
        if q:
            conditions.append("CAST(data AS TEXT) LIKE ? ESCAPE '\\'")
            args.append(escaped_like(q))
        if evidence_id:
            conditions.append(
                f"EXISTS (SELECT 1 FROM {array_values(self.db, 'findings.data', 'evidenceIds')} WHERE value=?)"
            )
            args.append(evidence_id)
        return " AND ".join(conditions), args

    def findings_page(self, subject_id="", funding="", q="", page=1, page_size=30):
        where, args = self.finding_filter(subject_id, funding, q)
        total = self.db.execute(
            "SELECT COUNT(*) FROM findings WHERE " + where, args
        ).fetchone()[0]
        return {
            "rows": self.findings(
                subject_id, funding, q, page_size, (page - 1) * page_size
            ),
            "total": total,
            "page": page,
            "pageSize": page_size,
            "note": "표시는 위반 확정이 아닌 추가 확인의 근거입니다.",
        }

    def findings(
        self, subject_id="", funding="", q="", limit=30, offset=0, evidence_id=""
    ):
        where, args = self.finding_filter(subject_id, funding, q, evidence_id)
        rows = records(
            self.db,
            "SELECT data FROM findings WHERE "
            + where
            + " ORDER BY id LIMIT ? OFFSET ?",
            [*args, limit, offset],
        )
        result = []
        for row in rows:
            f = json.loads(row["data"])
            observed = f.get("observed", {})
            if observed.get("merchantId"):
                observed["merchantId"] = public_merchant_id(observed["merchantId"])
            if self.config.pseudonyms:
                f["explanation"] = (
                    "규칙에 따라 추가 확인이 필요한 기록입니다. 근거 거래와 정상적인 설명을 함께 확인해 주세요."
                )
                if "merchantName" in observed:
                    observed["merchantName"] = "거래처(가명)"
                if "payee" in observed:
                    observed["payee"] = "거래처(가명)"
            f["reviewHistory"] = payload(self.db, "reviews", {}).get(f["id"], [])
            result.append(f)
        return result
