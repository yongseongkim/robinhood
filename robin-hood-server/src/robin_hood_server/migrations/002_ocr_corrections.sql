CREATE TABLE ocr_corrections (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    extraction_sha256 TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    data JSONB NOT NULL
);
CREATE INDEX ocr_corrections_document ON ocr_corrections(doc_id,created_at DESC);
