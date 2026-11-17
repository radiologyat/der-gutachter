# TODO / Projektstatus

Stand: 2026-11-17 (v1.0.0) — Forschungsprototyp, funktional abgeschlossen. Änderungen je
Version: `CHANGELOG.md`; Entwicklungsgeschichte: Git-Historie.

## Stand

- **Ablauf:** Ordner laden (PDF, Bilder, Word, RTF, Text, HTML, E-Mail) → Texterkennung
  → Gutachtenauftrag → Register → Extraktion mit Zitatprüfung → Aktenauszug (bearbeitbar,
  Herkunft je Eintrag) → regelbasierte Prüfung und KI-Prüfung → Gutachten nach Vorlage
  (IV, UVG, allgemein, AT) → optional KI-Vorentwurf → Word-Export.
- **Nachvollziehbarkeit:** Schrittstatus mit „veraltet“, „Alles aktualisieren“,
  Protokoll mit CSV-Export, Diagnose je Fall, jede Modellanfrage in `llm_calls`.
- **Betrieb:** Windows-Installer und Portable (CI-Build mit Selbsttest), Einrichtung mit
  Modell-Download oder USB-Import, Daten in `%LOCALAPPDATA%\DerGutachter`, Sicherung vor
  jeder Schema-Migration, Speicherfreigabe des Sprachmodells.
- **Sprachmodell:** Gemma 4 12B (QAT Q4_0) über llama.cpp, gewählt am 2026-11-17 nach
  einem Modellvergleich (`scripts/eval/compare_models.py`); rund 1,6-fache Rechenzeit
  gegenüber Qwen3.5-9B.
- **Tests:** 195 grün (`uv run pytest`), Lint sauber (`uv run ruff check`).

## Offen vor einem Einsatz

In dieser Reihenfolge:
1. **Ziel-Laptop** (RTX 5070 Laptop, 8 GB, Windows 11): Installer, CUDA-Build; läuft
   Gemma 4 12B vollständig auf der GPU, Laufzeit je Fall.
2. **Echte, anonymisierte Akten** (Scans, Handschrift, Fax); Prompts und Schwellen
   anhand der `llm_calls` nachschärfen.
3. **Eigene Vorlage und Schreibstil** der Gutachterin/des Gutachters.
4. **Rechtliche Kurzprüfung** (MDR-Zweckbestimmung, Haftung, Datenschutz) durch Anwalt.
5. Signatur über SignPath und Build-Attestierung statt selbstsigniertem Zertifikat.

## Bekannte Grenzen

- KI-Vorentwurf: inhaltliche Wiederholungen zwischen den Abschnitten (von den
  Prüfregeln grossteils abgefangen); Kausalitätsbegründung stützt sich auf
  Berichtsformulierungen, nicht auf eigene Bildbeurteilung.
- Geschlecht der versicherten Person wird nicht übergeben („Patientin“ bei Männern
  vereinzelt).
- Audio wird nur als Platzhalterseite aufgenommen (keine Transkription); Outlook-.msg
  nicht unterstützt.
- Hinweise erscheinen nicht direkt an der zugehörigen Aktenauszug-Zeile.
- `scripts/download_models.py` nutzt eigene Download-Logik statt `gutachten.downloads`.
- Apertus 1.5 (Swiss AI) nicht getestet: llama.cpp unterstützt die Architektur noch
  nicht offiziell.

## Konventionen (wichtig!)

- **Keine Netzwerk-Calls zur Laufzeit.** Patientendaten verlassen den Rechner nie.
- **Keine Aussage ohne Fundstelle**: jedes Fact/Finding/jeder Absatz zitiert
  `(page_id, block_id, quote)` — „Bl. N d. A."
- Ärztliches Urteil bleibt beim User: jeder Abschnitt braucht explizite Freigabe.
- Schema-Änderungen = neue Migration (`schema_vN.sql` + Eintrag in
  `database.MIGRATIONS`); läuft beim Connect auf existierende case.db.
- Tests nutzen synthetische deutsche Dokumente (`tests/conftest.py`) —
  **niemals** echte Patientendaten ins Repo.

## Datei-Map

| Pfad | Zweck |
|---|---|
| `src/gutachten/db/schema*.sql` | Datenmodell (Provenienz-Tabellen) |
| `src/gutachten/cases.py` | Fall-Lifecycle, Stage-Berechnung, Termine |
| `src/gutachten/ingest/pipeline.py` | Import, Hash, Dedupe, Render |
| `src/gutachten/ingest/convert.py` | Importbausteine Word/RTF/Text/HTML/E-Mail, Platzhalter |
| `src/gutachten/analysis/steps.py` | Schrittstatus, „veraltet“, Neuberechnung |
| `src/gutachten/analysis/proposals.py` | KI-Vorentwurf (Empfehlungen, Filter, Protokoll) |
| `src/gutachten/ocr/` | Engines (pdf_text, tesseract, vlm) + Runner |
| `src/gutachten/analysis/` | Phase 2: cover, segment, extract, timeline, runner |
| `src/gutachten/dates.py` | Datumserkennung DE/AT/CH (Beleg-Prüfung) |
| `src/gutachten/citations.py` | Zitat → Fundstelle (Block-IDs, BBox, Score) |
| `src/gutachten/llm/` | llama.cpp Client/Server, JSON-Schemas, Prompts |
| `src/gutachten/api/` | FastAPI (jobs = Hintergrund-Tasks) |
| `web/src/pages/` | Dashboard + CaseView (Tabs) |
| `web/src/components/` | Fallnavigation (CaseNav), Aktivitätsleiste, Übersicht/Akte/Register/Auszug/Hinweise/Untersuchung/Gutachten/Protokoll/Diagnose |
