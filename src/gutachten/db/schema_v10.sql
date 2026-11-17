-- v10: one-click pipeline — suggestions applied automatically are marked and can be
-- undone exactly (applied_json records what was changed).
ALTER TABLE suggestions ADD COLUMN auto INTEGER NOT NULL DEFAULT 0;
ALTER TABLE suggestions ADD COLUMN applied_json TEXT;
ALTER TABLE cases ADD COLUMN interview_json TEXT NOT NULL DEFAULT '{}';
