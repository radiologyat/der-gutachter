-- v7: Phase 3 — findings keep user decisions across re-runs; documents can be
-- excluded from the analysis (e.g. misfiled document of another patient).
ALTER TABLE findings ADD COLUMN fingerprint TEXT;
ALTER TABLE findings ADD COLUMN document_id INTEGER REFERENCES documents(id);
ALTER TABLE findings ADD COLUMN decided_at TEXT;
CREATE INDEX IF NOT EXISTS idx_findings_fp ON findings(case_id, fingerprint);
ALTER TABLE documents ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0;
