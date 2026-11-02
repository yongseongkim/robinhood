-- Applied transactionally inside the configured service schema.
-- Never touches public or other applications' schemas.
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS subjects (
    id TEXT PRIMARY KEY, name TEXT, display_name TEXT, type TEXT, source TEXT,
    org TEXT, role TEXT, term TEXT, party TEXT, district TEXT, details JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS merchants (
    id TEXT PRIMARY KEY, name TEXT, display_name TEXT, region TEXT, confidence TEXT,
    aliases JSONB, display_aliases JSONB, business_number TEXT, kind TEXT
);
CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, source TEXT, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS extras (
    subject_id TEXT PRIMARY KEY REFERENCES subjects(id), assets JSONB, activity JSONB
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY, date DATE, month TEXT, time TEXT, amount BIGINT NOT NULL,
    description TEXT, category TEXT, category_group TEXT, payee TEXT, payee_type TEXT,
    subject_id TEXT NOT NULL REFERENCES subjects(id), merchant_id TEXT REFERENCES merchants(id),
    funding_type TEXT NOT NULL, account TEXT, source TEXT, doc_id TEXT NOT NULL REFERENCES documents(id),
    row_ref TEXT, attendees INTEGER, payment TEXT, budget_item TEXT, flags JSONB, quality JSONB,
    duplicate_of TEXT, pair TEXT, retained_payment SMALLINT, is_meal SMALLINT, valid_period SMALLINT,
    weekday TEXT, holiday TEXT, receipt_no TEXT, category_source TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY, subject_id TEXT REFERENCES subjects(id), funding_type TEXT, data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS tx_report ON transactions(doc_id,date,subject_id);
CREATE INDEX IF NOT EXISTS tx_council ON transactions(source,funding_type,date);
CREATE INDEX IF NOT EXISTS tx_subject ON transactions(subject_id,funding_type,date);
CREATE INDEX IF NOT EXISTS tx_merchant ON transactions(merchant_id,funding_type,date);
CREATE INDEX IF NOT EXISTS tx_scope ON transactions(funding_type,date,duplicate_of,valid_period);
CREATE INDEX IF NOT EXISTS tx_places ON transactions(funding_type,is_meal,date,merchant_id);
CREATE INDEX IF NOT EXISTS finding_subject ON findings(subject_id,funding_type);
CREATE TABLE IF NOT EXISTS job_runs (
    id TEXT PRIMARY KEY, state TEXT NOT NULL, started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ, next_run_at TIMESTAMPTZ, data JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS job_runs_started ON job_runs(started_at DESC);
CREATE TABLE IF NOT EXISTS job_schedule (
    name TEXT PRIMARY KEY, next_run_at TIMESTAMPTZ NOT NULL, failures INTEGER NOT NULL DEFAULT 0
);
