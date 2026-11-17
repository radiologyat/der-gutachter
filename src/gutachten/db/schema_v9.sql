-- v9: report completeness — formal details, structured examination, structured
-- answers to the standard questions, diagnoses with ICD-10.
ALTER TABLE cases ADD COLUMN patient_name TEXT;        -- full name for the report (ref = pseudonym)
ALTER TABLE cases ADD COLUMN patient_address TEXT;
ALTER TABLE cases ADD COLUMN ahv_nr TEXT;
ALTER TABLE cases ADD COLUMN identity_check TEXT;      -- e.g. "Identitätskarte geprüft"
ALTER TABLE cases ADD COLUMN order_date TEXT;          -- Auftragsdatum
ALTER TABLE cases ADD COLUMN received_date TEXT;       -- Eingangsdatum
ALTER TABLE cases ADD COLUMN exam_date TEXT;           -- Explorationsdatum
ALTER TABLE cases ADD COLUMN exam_start TEXT;          -- HH:MM
ALTER TABLE cases ADD COLUMN exam_end TEXT;            -- HH:MM
ALTER TABLE cases ADD COLUMN interpreter TEXT;         -- language, empty = none
ALTER TABLE cases ADD COLUMN completed_date TEXT;      -- Fertigstellung
ALTER TABLE cases ADD COLUMN job_profile TEXT;         -- Anforderungsprofil bisherige Tätigkeit
ALTER TABLE cases ADD COLUMN exam_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE cases ADD COLUMN answers_json TEXT NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    ord INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    icd10 TEXT,
    laterality TEXT,            -- links|rechts|beidseits|na
    since TEXT,                 -- ISO date or year
    af_relevant INTEGER,        -- 1 = mit Auswirkung auf die Arbeitsfähigkeit, 0 = ohne, NULL = offen
    source TEXT NOT NULL DEFAULT 'eigen',   -- eigen|akte
    fact_id INTEGER REFERENCES facts(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- sections the expert edited are never regenerated automatically
ALTER TABLE draft_sections ADD COLUMN user_edited INTEGER NOT NULL DEFAULT 0;
