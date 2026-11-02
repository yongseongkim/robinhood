"""Build a disposable read model; publish only a complete validated database."""

from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from .config import Settings

SCHEMA = """
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE subjects(id TEXT PRIMARY KEY, name TEXT, display_name TEXT, type TEXT, source TEXT, org TEXT,
 role TEXT, term TEXT, party TEXT, district TEXT, details TEXT NOT NULL);
CREATE TABLE merchants(id TEXT PRIMARY KEY, name TEXT, display_name TEXT, region TEXT, confidence TEXT,
 aliases TEXT, display_aliases TEXT, business_number TEXT, kind TEXT);
CREATE TABLE documents(id TEXT PRIMARY KEY, source TEXT, data TEXT NOT NULL);
CREATE TABLE extras(subject_id TEXT PRIMARY KEY, assets TEXT, activity TEXT);
CREATE TABLE transactions(id TEXT PRIMARY KEY, date TEXT, month TEXT, time TEXT, amount INTEGER NOT NULL,
 description TEXT, category TEXT, category_group TEXT, payee TEXT, payee_type TEXT, subject_id TEXT,
 merchant_id TEXT, funding_type TEXT NOT NULL, account TEXT, source TEXT, doc_id TEXT, row_ref TEXT,
 attendees INTEGER, payment TEXT, budget_item TEXT, flags TEXT, quality TEXT, duplicate_of TEXT,
 pair TEXT, retained_payment INTEGER, is_meal INTEGER, valid_period INTEGER, weekday TEXT, holiday TEXT,
 receipt_no TEXT, category_source TEXT);
CREATE TABLE findings(id TEXT PRIMARY KEY, subject_id TEXT, funding_type TEXT, data TEXT NOT NULL);
"""


@contextmanager
def collection_lock(var):
    if isinstance(var, Settings):
        if var.postgres:
            from .postgres import collection_lock as postgres_lock

            with postgres_lock(var):
                yield
            return
        var = var.var
    var.mkdir(parents=True, exist_ok=True)
    with (var / "collection.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            from .postgres import JobAlreadyRunning

            raise JobAlreadyRunning("다른 수집·인덱스 작업이 실행 중입니다.") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read(path, fallback):
    return json.loads(path.read_text()) if path.exists() else fallback


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def public_merchant_id(internal):
    return "m-" + hashlib.sha256(internal.encode()).hexdigest()[:16]


def _pipeline(root):
    sys.path.insert(0, str(root / "pipeline"))
    from common import COUNCIL_HOSPITALITY, KA_HOSPITALITY, display_bizno
    from build_rank import _is_meal_place
    from councils import load_registry
    from rules import RULES

    return (
        COUNCIL_HOSPITALITY,
        KA_HOSPITALITY,
        display_bizno,
        _is_meal_place,
        load_registry,
        RULES,
    )


def build_index(config: Settings, *, locked=False):
    if locked:
        return _publish(config)
    with collection_lock(config):
        return _publish(config)


def _publish(config):
    if not config.postgres:
        return _build(config)
    from .postgres import publish

    config.var.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="postgres-stage-", dir=config.var
    ) as folder:
        staged = replace(
            config,
            database=Path(folder) / "stage.sqlite3",
            database_url="",
            job_database_url="",
        )
        result = _build(staged)
        publish(config, staged.database)
    # Never return a DSN, credentials or a deleted scratch path to callers/logs.
    return {**result, "database": "postgresql", "schema": config.database_schema}


def _build(config):
    council_food, political_food, mask_bizno, is_place, registry, rules = _pipeline(
        config.root
    )
    source = config.data
    required = [
        "subjects.json",
        "merchants.json",
        "documents.json",
        "expenditures.jsonl",
    ]
    for name in required:
        if not (source / name).is_file():
            raise FileNotFoundError(f"수집 자료가 없습니다: {name}")
    subjects = read(source / "subjects.json", [])
    merchants = {m["id"]: m for m in read(source / "merchants.json", [])}
    documents = read(source / "documents.json", [])
    if not subjects or not merchants or not documents:
        raise ValueError("빈 수집 자료는 조회 데이터로 발행하지 않습니다.")
    aliases = read(
        Path(__file__).with_name("pseudonyms.json"), {"people": {}, "merchants": {}}
    )
    people = {
        name: f"의원 {i + 1:03d}"
        for i, name in enumerate(
            sorted({s["name"] for s in subjects if s.get("type") == "LEGISLATOR"})
        )
    }
    people.update(aliases.get("people", {}))
    holder_names = sorted(
        {h["name"] for s in subjects for h in (s.get("holders") or []) if h.get("name")}
    )
    for i, name in enumerate(holder_names):
        people.setdefault(name, f"직책 보유자 {i + 1:03d}")
    mids = {mid: public_merchant_id(mid) for mid in merchants}
    pair_map = read(source / "reversal_pairs.json", {})
    pairs = {**pair_map, **{v: k for k, v in pair_map.items()}}
    assets = read(source / "assets.json", {"people": [], "source": {}})
    asset_map = {v["sid"]: v for v in assets["people"] if v.get("sid")}
    assembly = read(source / "assembly.json", {"subjects": {}, "summary": {}})
    subject_ids = {s["id"] for s in subjects}
    document_ids = {d["doc_id"] for d in documents}
    config.database.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix="dashboard-", suffix=".sqlite3", dir=config.database.parent
    )
    os.close(fd)
    target = Path(temporary)
    db = sqlite3.connect(target)
    try:
        db.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + SCHEMA)
        for subject in subjects:
            terms = subject.get("terms") or {}
            term = terms.get("제22대") or next(iter(reversed(terms.values())), {})
            display_name = people.get(subject["name"], subject["name"])
            if subject["type"] == "COUNCIL_MEMBER":
                member_name = (subject.get("role") or "").removesuffix("의원").strip()
                display_name = (
                    (subject.get("org") or "")
                    + " "
                    + people.get(
                        member_name,
                        "의원 "
                        + hashlib.sha256(subject["id"].encode()).hexdigest()[:5],
                    )
                )
            db.execute(
                "INSERT INTO subjects VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    subject["id"],
                    subject["name"],
                    display_name,
                    subject["type"],
                    subject.get(
                        "org_source",
                        "ka-money" if subject["type"] == "LEGISLATOR" else "",
                    ),
                    subject.get("org"),
                    subject.get("role"),
                    subject.get("term"),
                    term.get("party"),
                    term.get("district"),
                    packed(subject),
                ),
            )
            if subject["id"] in asset_map or subject["id"] in assembly["subjects"]:
                db.execute(
                    "INSERT INTO extras VALUES(?,?,?)",
                    (
                        subject["id"],
                        packed(asset_map.get(subject["id"])),
                        packed(assembly["subjects"].get(subject["id"])),
                    ),
                )
        for i, (mid, merchant) in enumerate(sorted(merchants.items())):
            name = merchant["name"]
            display = aliases.get("merchants", {}).get(name, f"거래처 {i + 1:05d}")
            variants = merchant.get("aliases") or []
            display_variants = [
                aliases.get("merchants", {}).get(v, display + f" 표기 {j + 1}")
                for j, v in enumerate(variants[:8])
            ]
            db.execute(
                "INSERT INTO merchants VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    mids[mid],
                    name,
                    display,
                    merchant.get("region"),
                    merchant.get("id_confidence"),
                    packed(variants[:8]),
                    packed(display_variants),
                    mask_bizno(merchant.get("bizno"), merchant.get("bizno_kind")),
                    merchant.get("kind"),
                ),
            )
        for doc in documents:
            db.execute(
                "INSERT INTO documents VALUES(?,?,?)",
                (doc["doc_id"], doc["source_id"], packed(doc)),
            )
        for finding in read(source / "findings.json", []):
            db.execute(
                "INSERT INTO findings VALUES(?,?,?,?)",
                (
                    finding["id"],
                    finding["subjectId"],
                    finding["fundingType"],
                    packed(finding),
                ),
            )
        batch, total = [], 0
        with (source / "expenditures.jsonl").open() as stream:
            for line in stream:
                if not line.strip():
                    continue
                e = json.loads(line)
                if e["subject_id"] not in subject_ids:
                    raise ValueError(f"연결되지 않은 지출 주체: {e['subject_id']}")
                mid = e.get("merchant_id")
                if mid and mid not in mids:
                    raise ValueError(f"연결되지 않은 거래처: {mid}")
                if e.get("doc_id") not in document_ids:
                    raise ValueError(f"연결되지 않은 출처 문서: {e.get('doc_id')}")
                flags = e.get("quality", {}).get("flags", [])
                category = e.get("category") or "미분류"
                food = category in (
                    political_food if e["source_id"] == "ka-money" else council_food
                )
                eligible = bool(food and mid and is_place(e, merchants))
                batch.append(
                    (
                        e["id"],
                        e.get("date"),
                        (e.get("date") or "")[:7],
                        e.get("time"),
                        e["amount"],
                        e.get("description"),
                        category,
                        category.split("_")[0],
                        e.get("payee_display"),
                        e.get("payee_type"),
                        e["subject_id"],
                        mids.get(mid),
                        e["funding_type"],
                        e.get("funding_account"),
                        e["source_id"],
                        e["doc_id"],
                        e.get("row_ref"),
                        e.get("attendees"),
                        e.get("payment_method"),
                        e.get("budget_item"),
                        packed(flags),
                        packed(e.get("quality") or {}),
                        e.get("duplicate_of"),
                        pairs.get(e["id"]),
                        int(
                            e["amount"] > 0
                            and e["id"] not in pairs
                            and not e.get("duplicate_of")
                        ),
                        int(eligible),
                        int("DATE_OUTSIDE_REPORT_PERIOD" not in flags),
                        e.get("weekday"),
                        e.get("holiday"),
                        e.get("receipt_no"),
                        e.get("category_source"),
                    )
                )
                if len(batch) >= 2000:
                    db.executemany(
                        "INSERT INTO transactions VALUES(" + ",".join("?" * 31) + ")",
                        batch,
                    )
                    total += len(batch)
                    batch.clear()
        if batch:
            db.executemany(
                "INSERT INTO transactions VALUES(" + ",".join("?" * 31) + ")", batch
            )
            total += len(batch)
        if not total:
            raise ValueError("지출이 없는 인덱스는 발행하지 않습니다.")
        db.executescript("""
        CREATE INDEX tx_report ON transactions(doc_id,date,subject_id);
        CREATE INDEX tx_council ON transactions(source,funding_type,date);
        CREATE INDEX tx_subject ON transactions(subject_id,funding_type,date);
        CREATE INDEX tx_merchant ON transactions(merchant_id,funding_type,date);
        CREATE INDEX tx_scope ON transactions(funding_type,date,duplicate_of,valid_period);
        CREATE INDEX tx_places ON transactions(funding_type,is_meal,date,merchant_id);
        CREATE INDEX finding_subject ON findings(subject_id,funding_type);
        """)
        geo_path = config.root / "site/data/geo.js"
        geo = {}
        if geo_path.exists():
            js = geo_path.read_text()
            geo = json.loads(js[js.index(",") + 1 : js.rindex(")")])
        counts = dict(
            db.execute(
                "SELECT funding_type,COUNT(*) FROM transactions WHERE duplicate_of IS NULL GROUP BY funding_type"
            )
        )
        metadata = {
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "counts": counts,
            "registry": registry(),
            "rules": rules,
            "funding": read(source / "funding_types.json", {}),
            "fiscal": read(source / "fiscal.json", {}),
            "geo": geo,
            "asset_source": assets.get("source"),
            "assembly_summary": assembly.get("summary"),
            "people_aliases": people,
            "asset_people": assets["people"],
            "reviews": read(config.root / "data/reviews.json", {}),
        }
        for key, value in metadata.items():
            db.execute("INSERT INTO metadata VALUES(?,?)", (key, packed(value)))
        db.commit()
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("조회 인덱스 무결성 검사에 실패했습니다.")
        db.close()
        with target.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(target, config.database)
        return {
            "transactions": total,
            "counted": sum(counts.values()),
            "database": str(config.database),
        }
    finally:
        db.close()
        target.unlink(missing_ok=True)
