# Änderungen

Forschungsprototyp, nicht für den produktiven Einsatz. Einzelheiten in den Commits.

## 1.0.0 — 2026-11-17
- Erste Version 1 des Forschungsprototyps; funktional wie 0.9.9.
- Öffentliches Repository als neuer, bereinigter Stand veröffentlicht; frühere
  Vorabversionen (0.9.x) dort entfernt.

## 0.9.9 — 2026-11-17
- **Sprachmodell Gemma 4 12B** statt Qwen3.5-9B: in einem Modellvergleich die
  folgerichtigsten Empfehlungen; rund 1,6-fache Rechenzeit. Download ca. 7 GB über die Einrichtung (bestehende Installationen laden
  es dort nach). Das optionale Analysemodell Qwen3.5-35B-A3B entfällt.
- KI-Vorentwurf: Abwägung der Gelegenheitsursache eindeutig benannt („für den
  Vorzustand spricht“ / „für das Ereignis als wesentliche Ursache spricht“) und nur bei
  Kausalitätsfragen; Modellartefakte („refs“, leere Klammern) werden entfernt.
- Fragen aus dem Gutachtenauftrag ohne übernommene Nummerierung („1.“, „a)“).

## 0.9.8 — 2026-11-17
- Programmsymbol (G-Zeichen) für Programmdatei, Installer und Fenster.
- Gutachtentitel nach Fachgebiet („Orthopädisch-traumatologisches Gutachten“) mit
  Untertitel je Auftragsart (IV monodisziplinär Art. 44 ATSG, UVG, Gerichtsgutachten);
  eigener Titel in der Einrichtung.
- Zeile „Rechtsgebiet: Schweiz“ aus bestehenden und neuen Texten entfernt.
- Arbeitsspeicher des Sprachmodells wird zuverlässig freigegeben: verwaiste Modellprozesse
  beim Start beendet, unter Windows an die App gebunden, Entladen nach 20 Minuten ohne Nutzung.
- Falldatenbank wird vor jeder Aktualisierung durch eine neuere Version gesichert
  (`backups/`, die letzten drei bleiben).
- Französische und italienische Unterlagen; gleiche Angaben aus mehreren Quellen
  zusammengeführt (verschiedene Untersuchungen desselben Tages bleiben getrennt);
  Abschnittsgrösse der Extraktion einstellbar (`GUTACHTEN_CHUNK_CHARS`).
- README und Installationsanleitung überarbeitet.

## 0.9.7 — 2026-11-16
- Texterkennung unter Windows bei Pfaden mit Leerzeichen oder Umlauten repariert
  (Tesseract direkt, ohne Pfade in Argumenten); Fehler in der Diagnose sichtbar.
- Word-Export neu gesetzt: klassische Typografie, schwarz-weiss, Kopf- und Fusszeile.
- „Deckblatt“ heisst „Gutachtenauftrag“, Seiten manuell wählbar; „Unterlagen hinzufügen“
  im Schritt Akte.

## 0.9.6 — 2026-11-16
- „Alles aktualisieren“: erkennt neue Seiten und Änderungen und rechnet nur nach,
  was fehlt oder veraltet ist.
- Eine Fallnavigation mit Gesamtfortschritt, „Jetzt / Danach“ und „Es fehlt noch“;
  kompakte Aktivitätsleiste; Ordner-Dialog in zwei Schritten.
- Export im Programmfenster über einen Speichern-Dialog.

## 0.9.5 — 2026-11-16
- Laufende Arbeit sichtbar (Schritt, Dauer, Restzeit), unterbrochene Läufe setzen fort,
  Warteschlange für mehrere Fälle; Gutachtenauftrag wird zuerst gelesen.
- Diagnose je Fall; robustere Erkennung der NVIDIA-Grafikkarte.

## 0.9.4 — 2026-11-16
- Abwägung der Gelegenheitsursache, Markierung von Widersprüchen, medizinische
  Entscheidungsgrundlage nach Dokumentart.

## 0.9.3 — 2026-11-15
- Status-quo-Definition, fallweite Konsistenz, abweichende Beurteilungen, KI-Prüfung v2.

## 0.9.2 — 2026-11-15
- Windows-Portable startet auch bei aus dem Internet geladenen Dateien (Mark of the Web).

## 0.9.1 — 2026-11-15
- KI-Prüfung (inhaltliche Hinweise mit Fundstelle); Korrekturen am KI-Vorentwurf.

## 0.9.0 — 2026-11-15
- Erste veröffentlichte Fassung des Forschungsprototyps.
