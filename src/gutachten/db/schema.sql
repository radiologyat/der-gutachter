-- Der Gutachter — per-case SQLite schema.
-- One case.db per case under cases/<case_id>/. Everything traceable.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,               -- short slug, e.g. '2024-mueller'
    title TEXT NOT NULL,
    patient_ref TEXT,                  -- pseudonym/initials chosen by the user
    jurisdiction TEXT,                 -- 'CH' | 'AT' | 'DE'
    case_type TEXT,                    -- 'unfall' | 'invaliditaet' | 'haftpflicht' | 'sonstiges'
    accident_date TEXT,                -- ISO date; anchor for causality tagging
    auftraggeber TEXT,                 -- court / insurer
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Beweisfragen / Fragenkatalog of the Auftraggeber; each must be answered.
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    ord INTEGER NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'    -- 'open' | 'answered' | 'skipped'
);

-- Every input file: scanned PDFs/images AND non-scan inputs (dictation, notes).
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    kind TEXT NOT NULL DEFAULT 'scan',      -- 'scan' | 'note' | 'dictation'
    filename TEXT NOT NULL,            -- stored name inside inbox/
    orig_name TEXT,                    -- filename as uploaded by the user
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ingested',-- 'ingested' | 'duplicate' | 'error'
    duplicate_of INTEGER REFERENCES sources(id),
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sources_sha ON sources(sha256);

-- Pages carry a stable global sequence = "Bl. N d.A." citation numbering.
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    page_no INTEGER NOT NULL,            -- page within the source file
    global_seq INTEGER NOT NULL,         -- "Bl. <global_seq> d.A."
    image_path TEXT,                     -- pages/P0001.png relative to case dir
    width INTEGER, height INTEGER,
    rotation INTEGER NOT NULL DEFAULT 0, -- detected orientation correction
    phash TEXT,                          -- perceptual hash for page dedupe
    has_embedded_text INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending'|'ocr_done'|'review'|'manual'
    UNIQUE (case_id, global_seq)
);
CREATE INDEX IF NOT EXISTS idx_pages_case ON pages(case_id, global_seq);

-- Every OCR execution is logged for the audit trail.
CREATE TABLE IF NOT EXISTS ocr_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    engine TEXT NOT NULL,               -- 'pdf_text' | 'tesseract' | 'vlm:<model>'
    engine_version TEXT,
    model_id TEXT,
    prompt_version TEXT,
    status TEXT NOT NULL DEFAULT 'ok',  -- 'ok' | 'error'
    error TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

-- Text blocks with bounding boxes (normalized 0..1 coordinates).
CREATE TABLE IF NOT EXISTS ocr_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    run_id INTEGER NOT NULL REFERENCES ocr_runs(id),
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    confidence REAL,
    block_type TEXT NOT NULL DEFAULT 'line'   -- 'line' | 'paragraph' | 'table_cell'
);
CREATE INDEX IF NOT EXISTS idx_blocks_page ON ocr_blocks(page_id, seq);

-- Current best text per page (OCR output or manual correction).
CREATE TABLE IF NOT EXISTS page_text (
    page_id INTEGER PRIMARY KEY REFERENCES pages(id),
    text_md TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'none',      -- 'ocr' | 'manual' | 'embedded'
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Logical documents segmented from the page stream.
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    title TEXT,
    doc_type TEXT,                     -- 'arztbrief'|'op_bericht'|'radiologie'|'labor'|'rezept'|'korrespondenz'|'formular'|'sonstiges'
    doc_date TEXT,
    author TEXT,
    institution TEXT,
    start_seq INTEGER, end_seq INTEGER, -- global_seq range
    created_by TEXT NOT NULL DEFAULT 'pipeline',
    reviewed INTEGER NOT NULL DEFAULT 0
);

-- Structured facts extracted per document/page (Phase 2).
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    document_id INTEGER REFERENCES documents(id),
    page_id INTEGER REFERENCES pages(id),
    fact_date TEXT,
    event_category TEXT,               -- 'vorbefund'|'trauma'|'diagnostik'|'op'|'konservativ'|'reha'|'begutachtung'|'korrespondenz'
    causality TEXT,                    -- 'vorschaden'|'unfallkausal'|'kombiniert'|'unklar'|'none'
    body_region TEXT,
    laterality TEXT,                   -- 'links'|'rechts'|'beidseits'|'na'
    icd10 TEXT,
    title TEXT,
    summary TEXT,
    quote TEXT,                        -- verbatim source passage
    confidence REAL,
    created_by TEXT NOT NULL DEFAULT 'pipeline',
    reviewed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_facts_case ON facts(case_id, fact_date);

-- Materialized Aktenauszug (editable; built from facts).
CREATE TABLE IF NOT EXISTS timeline_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    entry_date TEXT NOT NULL,
    date_end TEXT,                     -- range end, e.g. Reha stays
    category TEXT,
    causality TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    citations TEXT NOT NULL DEFAULT '[]',  -- JSON [{page_id, block_id, quote}]
    sort REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_timeline_case ON timeline_entries(case_id, entry_date);

-- Inconsistency findings (Phase 3).
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    type TEXT NOT NULL,                -- 'predates_accident'|'laterality_conflict'|'identity_mismatch'|'date_contradiction'|'claim_conflict'|'coverage_gap'
    severity TEXT NOT NULL DEFAULT 'medium', -- 'low'|'medium'|'high'
    claim TEXT NOT NULL,
    source_a TEXT NOT NULL DEFAULT '{}',     -- JSON citation
    source_b TEXT,                           -- JSON citation
    explanation TEXT,
    status TEXT NOT NULL DEFAULT 'open',     -- 'open'|'accepted'|'rejected'
    created_by TEXT NOT NULL DEFAULT 'pipeline',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Report draft sections with Freigabe workflow (Phase 4).
CREATE TABLE IF NOT EXISTS draft_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    ord INTEGER NOT NULL,
    section_key TEXT NOT NULL,         -- 'anamnese_aktenlage'|'anamnese_patient'|'befund'|'diagnosen'|'epikrise'|'beurteilung'|...
    title TEXT NOT NULL,
    content_md TEXT NOT NULL DEFAULT '',
    citations TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'empty', -- 'empty'|'draft'|'reviewed'|'approved'
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Full audit trail: every pipeline action and user decision.
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    actor TEXT NOT NULL DEFAULT 'system',  -- 'system' | 'user'
    action TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id, ts);
