-- v14: same as v13 for the older label form "**Rechtsgebiet:** Schweiz" on its own line.
UPDATE draft_sections SET content_md = REPLACE(content_md, char(10) || '**Rechtsgebiet:** Schweiz', '')
  WHERE content_md LIKE '%**Rechtsgebiet:** Schweiz%';
UPDATE draft_sections SET content_md = REPLACE(content_md, char(10) || '**Rechtsgebiet:** Österreich', '')
  WHERE content_md LIKE '%**Rechtsgebiet:** Österreich%';
