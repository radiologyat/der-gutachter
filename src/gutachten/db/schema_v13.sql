-- v13: the country is not stated in the report (evident to client and court).
-- Removes it from texts generated before 0.9.6, including approved sections.
UPDATE draft_sections SET content_md = REPLACE(content_md, ' · Rechtsgebiet: Schweiz', '')
  WHERE content_md LIKE '%Rechtsgebiet: Schweiz%';
UPDATE draft_sections SET content_md = REPLACE(content_md, ' · Rechtsgebiet: Österreich', '')
  WHERE content_md LIKE '%Rechtsgebiet: Österreich%';
UPDATE draft_sections SET content_md = REPLACE(content_md, ' · Rechtsgebiet: Deutschland', '')
  WHERE content_md LIKE '%Rechtsgebiet: Deutschland%';
