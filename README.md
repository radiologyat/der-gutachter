# Der Gutachter

> **Forschungsprototyp · kein Medizinprodukt · keine Gewährleistung**
>
> Nicht-kommerzielles Open-Source-Projekt (AGPL-3.0). Alle Ergebnisse sind
> Entwürfe und Hinweise, die eine qualifizierte Fachperson an der Originalakte
> prüfen muss. Die fachliche und rechtliche Verantwortung für ein Gutachten liegt
> allein bei der Person, die es unterzeichnet. Die Nutzung erfolgt auf eigene
> Verantwortung; massgeblich ist der [Haftungsausschluss](DISCLAIMER.md).
>
> *Research prototype · not a medical device · no warranty. Non-commercial
> open source (AGPL-3.0). See [DISCLAIMER.md](DISCLAIMER.md).*

**Der Gutachter** ist eine lokal betriebene Software zur Vorbereitung orthopädischer
Gutachten für Sozialversicherungen, Haftpflichtversicherer und Gerichte, primär in der
Schweiz, ergänzend in Österreich. Sie erfasst und paginiert die Akte, erstellt einen
chronologischen Aktenauszug mit Fundstellen, weist auf Widersprüche und
Abgrenzungsfragen hin und bereitet den Gutachtentext nach der Vorlage der jeweiligen
Auftragsart vor. Sämtliche Verarbeitung erfolgt auf dem Rechner der Sachverständigen.

*English: locally operated software for the preparation of orthopaedic expert opinions
(Switzerland, Austria). It paginates the case file, builds a cited chronology, flags
contradictions and prepares the report according to the assignment type. All
processing takes place on the expert's computer.*

## Arbeitsablauf

Mit „Akte-Ordner öffnen“ wird ein Fall angelegt und die Auswertung gestartet. Im Fall
führt eine Navigation durch sechs Arbeitsschritte; jeder Schritt zeigt seinen Stand
(offen, zu prüfen, erledigt, veraltet) und ist manuell korrigierbar.

1. **Akte.** Übernahme von PDF-Dateien, Scans und Bildern, Word-, RTF-, Text- und
   HTML-Dokumenten sowie E-Mails einschliesslich Anhängen. Jede Seite erhält eine
   Blattzahl („Bl. N d. A.“). Der Text wird lokal erkannt und ist korrigierbar.
   Nicht lesbare Formate werden als Platzhalterseite geführt.
2. **Dokumente.** Register mit Dokumenttyp und Datum. Die Angaben des
   Gutachtenauftrags (Auftraggeber, Personalien, Ereignisdatum, Fristen, Fragestellung)
   werden mit Fundstelle übernommen; jede Übernahme ist einzeln widerrufbar. Die
   Auftragsart wird aus dem Auftraggeber abgeleitet.
3. **Aktenauszug.** Chronologische Darstellung aller belegten Angaben mit Fundstelle
   und Herkunftsvermerk. Einträge können ergänzt, berichtigt (das Original bleibt
   erhalten), ausgeschlossen und als geprüft markiert werden.
4. **Hinweise.** Regelbasierte Prüfung (Personalien, Vorbefunde, Seitenangaben, Daten,
   Behandlungslücken) und modellgestützte Prüfung inhaltlicher Auffälligkeiten
   (Widersprüche, Abgrenzung von Vorschäden, Zwischenverläufe, Kausalketten, fehlende
   Unterlagen, verspätete Meldung). Jeder Hinweis nennt beide Fundstellen und ist zu
   bestätigen oder zu verwerfen.
5. **Untersuchung.** Befragungsleitfaden aus der Aktenlage, strukturierte
   Befunderhebung (Neutral-0-Methode), Diagnosen mit ICD-10-GM, Standardfragen der
   Auftragsart.
6. **Gutachten.** Abschnitte nach Vorlage (IV gemäss KSVI, Unfallversicherung,
   Haftpflicht/Gericht; Österreich als Grundgerüst). Optional ein KI-Vorentwurf mit
   Empfehlung, Begründung und offenen Prüfpunkten; Fragen, die eine Untersuchung
   voraussetzen, werden ausschliesslich als vorläufige Einschätzung nach Aktenlage
   formuliert. Freigabe abschnittsweise, Export als Word-Dokument.

„Alles aktualisieren“ berücksichtigt neue Unterlagen und Korrekturen, berechnet nur die
betroffenen Schritte neu und weist anschliessend die offenen Punkte aus. Eigene Texte
und Freigaben bleiben unverändert. Unterbrochene Auswertungen werden fortgesetzt;
mehrere Akten werden nacheinander bearbeitet. Das Protokoll verzeichnet jede Aktion der
Sachverständigen, des Programms und des Sprachmodells und kann als Beilage zur
Dokumentation des KI-Einsatzes exportiert werden.

## Grundsätze

- **Lokale Verarbeitung.** Texterkennung (Tesseract) und Sprachmodell (Gemma 4 12B über
  llama.cpp) laufen auf dem Gerät. Eine Netzwerkverbindung wird nur für das einmalige,
  ausdrücklich ausgelöste Herunterladen der Modelle benötigt.
- **Belegpflicht.** Jede Angabe muss mit wörtlichem Zitat und Datum in der Akte
  nachweisbar sein; andernfalls wird sie nicht übernommen. Modellaussagen ohne gültige
  Fundstelle werden verworfen und protokolliert.
- **Entscheidung bei der Sachverständigen.** Modellvorschläge sind als solche
  gekennzeichnet und sperren die Freigabe, bis sie übernommen oder ersetzt sind.
  Befragung und Untersuchungsbefund werden nicht erzeugt. Rechtsfragen (Adäquanz,
  Leistungsentscheide) werden als solche ausgewiesen und nicht medizinisch beantwortet.
- **Nachvollziehbarkeit.** Jeder Arbeitsschritt ist mit Ergebnis, Herkunft und
  Korrekturmöglichkeit einsehbar.

## Einsatzgrenzen

Forschungsprototyp, nicht validiert, kein Medizinprodukt.

Die Software dient der Vorbereitung: belegter Aktenauszug, Hinweise, Gliederung nach
Vorlage und begründete Entwürfe. Sie ersetzt weder die persönliche Untersuchung noch
die eigene Beurteilung der Bildgebung noch die abschliessende Würdigung durch die
Sachverständige oder den Sachverständigen. Nicht erprobt sind bislang reale Akten
(Handschrift, Faxqualität) und der Betrieb auf der vorgesehenen Windows-Hardware mit
NVIDIA-Grafikkarte. Offene Punkte: [TODO.md](TODO.md).

## Installation (Windows 11)

Anleitung für Anwenderinnen und Anwender: [docs/INSTALLATION.md](docs/INSTALLATION.md).
Nach der Installation und der Bestätigung des Haftungsausschlusses lädt die Einrichtung
die Modelle herunter oder übernimmt sie offline von einem Datenträger.

Installer und portable Fassung stehen unter
[Releases](https://github.com/radiologyat/der-gutachter/releases) zur Verfügung. Sie
sind mit einem selbstsignierten Zertifikat signiert; Zertifikat und Skript zur
Hinterlegung als vertrauenswürdig liegen in [packaging/signing/](packaging/signing/).

## Entwicklung

Voraussetzungen: [uv](https://docs.astral.sh/uv/), Node.js, Tesseract, llama.cpp.

```bash
# macOS
brew install llama.cpp tesseract
uv sync
uv run python scripts/download_models.py        # Tesseract-Sprachdaten + Gemma 4 12B (~7 GB)
(cd web && npm install && npm run build)
uv run --group desktop python -m gutachten.desktop   # App-Fenster
# oder nur der Server:  uv run python -m gutachten.api.app  → http://127.0.0.1:8077
```

Windows-Entwicklungsumgebung: `scripts\setup_windows.ps1`.

| Befehl | Zweck |
|---|---|
| `uv run pytest` | Tests (mit einem simulierten Modell; kein Sprachmodell erforderlich) |
| `uv run ruff check` | Lint |
| `uv run python scripts/eval/run_eval.py` | Messung mit echtem Modell an einer synthetischen Akte |
| `uv run python scripts/eval/run_cases.py` | Alle Testfälle der Arbeitsliste auswerten und bewerten |
| `uv run python scripts/import_samples.py` | Lokale Testakten als Fälle anlegen |
| `uv run --group build --group desktop pyinstaller packaging/gutachten.spec` | App-Bundle bauen |

### Aufbau

```
src/gutachten/
  ingest/      Import, Prüfsummen, Seitenbilder, Seiten-Dubletten
  ocr/         Textebene / Tesseract / Vision-Modell, Prüf-Queue
  analysis/    Gutachtenauftrag, Register, Extraktion, Aktenauszug, Prüfung, Entwurf
  citations.py Zitat → Fundstelle (Blatt, Textblock, Bildausschnitt)
  dates.py     Datumserkennung CH/AT/DE (Belegprüfung)
  setup.py     Einrichtung: Hardware-Check, Modell-Download / Offline-Import
  desktop.py   App-Fenster (pywebview), Start/Stopp, Selbsttest
  api/         FastAPI (nur 127.0.0.1)
web/           Oberfläche (React)
packaging/     PyInstaller, Inno-Setup-Installer, Signierung, Laufzeit-Abhängigkeiten
```

Daten eines Falls: `cases/<id>/` mit `inbox/` (Originale), `pages/` (Blattbilder),
`case.db` (SQLite inkl. Audit-Log) und `exports/`. In der installierten App liegt alles
unter `%LOCALAPPDATA%\DerGutachter`, nie im Programmordner.

Konfiguration über Umgebungsvariablen: `GUTACHTEN_HOME` (Falldaten, z. B. auf einem
BitLocker-Laufwerk), `GUTACHTEN_MODELS`, `LLAMA_SERVER_BIN`, `TESSERACT_CMD`,
`GUTACHTEN_EXTRACT_MODEL`, `GUTACHTEN_EXTRACT_CTX`.

## Testdaten

Die Tests verwenden ausschliesslich frei erfundene Akten; Namen, Einrichtungen, Daten
und Befunde sind fiktiv, jedes erzeugte Testdokument trägt den Vermerk „Fiktives
Testdokument“ ([tests/TESTDATA.md](tests/TESTDATA.md)).

Dieses Repository enthält keine Patientendaten, keine Gerichtsentscheide und keine
realen Fällen nachgebildeten Akten. Eigene Testakten gehören in den Ordner `samples/`,
der von der Versionsverwaltung ausgeschlossen ist.

## Lizenz

[AGPL-3.0-or-later](LICENSE) · Drittkomponenten und Modelle: [NOTICE](NOTICE) ·
Haftungsausschluss: [DISCLAIMER.md](DISCLAIMER.md) · Sicherheitslücken vertraulich
melden: [SECURITY.md](SECURITY.md)
