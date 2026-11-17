-- v2: workflow metadata — patient DOB + case dates (Fristen/Termine).
ALTER TABLE cases ADD COLUMN patient_dob TEXT;

CREATE TABLE IF NOT EXISTS case_dates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    kind TEXT NOT NULL DEFAULT 'termin',    -- 'begutachtung'|'frist'|'termin'|'sonstiges'
    date TEXT NOT NULL,
    label TEXT,
    done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_dates_case ON case_dates(case_id, date);
