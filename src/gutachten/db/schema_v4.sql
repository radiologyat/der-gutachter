-- v4: Phase 2 — Registrierung, Fakt-Extraktion, Aktenauszug, Deckblatt-Vorschläge.

-- documents: identity fields (for Phase-3 mismatch checks) + how the boundary was found
ALTER TABLE documents ADD COLUMN patient_name TEXT;
ALTER TABLE documents ADD COLUMN patient_dob TEXT;
ALTER TABLE documents ADD COLUMN boundary_reason TEXT;  -- 'source'|'page_marker'|'llm'|'fallback'
ALTER TABLE documents ADD COLUMN verify_note TEXT;
ALTER TABLE documents ADD COLUMN prompt_version TEXT;
ALTER TABLE documents ADD COLUMN model_id TEXT;

-- facts: citation verification result
ALTER TABLE facts ADD COLUMN block_ids TEXT NOT NULL DEFAULT '[]';
ALTER TABLE facts ADD COLUMN bbox TEXT;                -- JSON [x0,y0,x1,y1] normalized
ALTER TABLE facts ADD COLUMN quote_score REAL;
ALTER TABLE facts ADD COLUMN verified INTEGER NOT NULL DEFAULT 0;  -- quote AND date found in Akte
ALTER TABLE facts ADD COLUMN verify_note TEXT;          -- why not verified
ALTER TABLE facts ADD COLUMN prompt_version TEXT;
ALTER TABLE facts ADD COLUMN model_id TEXT;

-- timeline: rebuilds replace only untouched pipeline rows
ALTER TABLE timeline_entries ADD COLUMN created_by TEXT NOT NULL DEFAULT 'pipeline';
ALTER TABLE timeline_entries ADD COLUMN edited INTEGER NOT NULL DEFAULT 0;
ALTER TABLE timeline_entries ADD COLUMN laterality TEXT;
ALTER TABLE timeline_entries ADD COLUMN body_region TEXT;

-- Every LLM call: input reference + raw structured output (audit / reproducibility).
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    stage TEXT NOT NULL,             -- 'page_analysis'|'fact_extract'|'cover'
    ref TEXT,                        -- e.g. 'Bl. 12' or 'doc 3 chunk 1'
    prompt_version TEXT NOT NULL,
    model_id TEXT,
    output_json TEXT,
    status TEXT NOT NULL DEFAULT 'ok',   -- 'ok'|'error'
    error TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_case ON llm_calls(case_id, stage);

-- Proposals the user must confirm (e.g. from the Deckblatt) — never auto-applied.
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    kind TEXT NOT NULL,              -- 'case_field'|'date'|'question'
    payload TEXT NOT NULL,           -- JSON, e.g. {"field":"auftraggeber","value":"..."}
    citation TEXT,                   -- JSON citation or null
    verified INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',  -- 'open'|'accepted'|'rejected'
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
