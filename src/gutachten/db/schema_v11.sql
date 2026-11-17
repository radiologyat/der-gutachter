-- v11: traceable, correctable Aktenauszug and step states.
-- original_json: the pipeline's version before the first manual change (restorable).
-- excluded: kept for the record but not used downstream. reviewed: checked by the expert.
ALTER TABLE timeline_entries ADD COLUMN original_json TEXT;
ALTER TABLE timeline_entries ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0;
ALTER TABLE timeline_entries ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE timeline_entries ADD COLUMN updated_at TEXT;
-- ran_at: when the step last ran; changed_at: when its output last changed (run or
-- manual edit). A step is stale when an upstream step changed after it ran.
CREATE TABLE IF NOT EXISTS step_marks (
    case_id TEXT NOT NULL REFERENCES cases(id),
    step TEXT NOT NULL,
    ran_at TEXT,
    changed_at TEXT,
    PRIMARY KEY (case_id, step)
);
