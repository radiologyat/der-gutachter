-- v6: page-level duplicates (same page filed twice). The page keeps its Bl.-number
-- (citations stay stable) but is skipped for extraction.
ALTER TABLE pages ADD COLUMN duplicate_of INTEGER REFERENCES pages(id);
ALTER TABLE pages ADD COLUMN duplicate_score REAL;
