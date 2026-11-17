-- v8: Phase 4 — draft sections carry generation provenance, open warnings and
-- approval metadata.
ALTER TABLE draft_sections ADD COLUMN kind TEXT NOT NULL DEFAULT 'manual';  -- data|narrative|basis|questions|manual
ALTER TABLE draft_sections ADD COLUMN warnings TEXT NOT NULL DEFAULT '[]';  -- JSON list
ALTER TABLE draft_sections ADD COLUMN prompt_version TEXT;
ALTER TABLE draft_sections ADD COLUMN model_id TEXT;
ALTER TABLE draft_sections ADD COLUMN generated_at TEXT;
ALTER TABLE draft_sections ADD COLUMN approved_at TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_draft_key ON draft_sections(case_id, section_key);
