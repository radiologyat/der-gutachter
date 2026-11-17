-- v5: periods (Hospitalisation, Reha, Arbeitsunfähigkeit) carry an end date.
ALTER TABLE facts ADD COLUMN fact_date_end TEXT;
