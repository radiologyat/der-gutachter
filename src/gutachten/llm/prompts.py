# SPDX-License-Identifier: AGPL-3.0-or-later
"""Versioned prompt templates. Bump the version when a prompt changes —
the version string is stored with every artifact for the audit trail."""

PAGE_ANALYSIS_VERSION = "page-analysis-v2"
FACT_EXTRACT_VERSION = "fact-extract-v4"
COVER_V1 = "cover-v1"
NARRATIVE_VERSION = "draft-narrative-v2"
BASIS_VERSION = "draft-basis-v2"

SYSTEM = (
    "Du bist ein sorgfältiger Assistent für orthopädische Gutachten. "
    "Du gibst nur wieder, was wörtlich in den Unterlagen steht, und erfindest nichts. "
    "Antworte ausschliesslich im vorgegebenen JSON-Schema."
)

PAGE_ANALYSIS_PROMPT = """\
Eine Gutachterakte ist ein Stapel gescannter Seiten. Entscheide für die AKTUELLE
Seite, ob hier ein neues Dokument beginnt (neuer Briefkopf, neuer Absender,
neues Datum, neuer Betreff) oder ob sie das vorherige Dokument fortsetzt.

Beschreibe ausserdem das Dokument, zu dem die aktuelle Seite gehört:
- doc_type (genau eine Kategorie):
  arztbrief = Arztbrief/Zuweisung/Sprechstundenbericht einer Praxis oder Klinik
  notfallbericht = Bericht einer Notfallstation / Erstversorgung
  austrittsbericht = Austritts-/Entlassungsbericht nach Spital- ODER Reha-Aufenthalt
  op_bericht = NUR der Operationsbericht selbst (Eingriff, Operateur, Verlauf der OP)
  radiologie = Röntgen-, CT-, MRI-, Ultraschallbefund
  labor = Laborwerte
  rezept = Verordnung (Medikamente, Physiotherapie, Hilfsmittel)
  gutachten = früheres Gutachten / IV-/SUVA-Stellungnahme
  gericht = Gerichtsschreiben, Gutachtenauftrag, Beweisbeschluss
  versicherung = Schreiben oder Formular einer Versicherung (Schadenmeldung, Entscheid)
  korrespondenz = sonstige Briefe (Anwalt, Patient)
  formular = sonstiges Formular; sonstiges = alles andere
- title: kurze Bezeichnung, z. B. "Arztbrief Orthopädie" oder "MRI Knie links"
- doc_date: Datum des Dokuments als ISO (JJJJ-MM-TT), nur wenn auf der Seite angegeben, sonst null
- author, institution, patient_name, patient_dob: nur wenn auf der Seite angegeben, sonst null

Ende der VORHERIGEN Seite:
<<<
{prev_tail}
>>>

AKTUELLE Seite (Bl. {global_seq} d. A.):
<<<
{page_text}
>>>
"""

FACT_EXTRACT_PROMPT = """\
Extrahiere die medizinisch und gutachterlich relevanten Sachverhalte aus dem
folgenden Dokument einer Gutachterakte (orthopädische Begutachtung).
Unfalltag des Falls: {accident_date}
Dokument: {doc_title} ({doc_type}, Datum: {doc_date})

Ziel ist ein Aktenauszug für das Gutachten: wenige, aussagekräftige Einträge.
- EIN Eintrag pro Ereignis: Unfallhergang; Untersuchung/Bildgebung mit Ergebnis;
  Diagnose(n) des Dokuments; Eingriff; Behandlungsphase (Physiotherapie, Reha,
  Hospitalisation); Arbeitsunfähigkeit/Arbeitsfähigkeit; Leistungsentscheid.
- Einzelheiten (Befunddetails, Medikamente, Hilfsmittel, Normalbefunde) gehören in
  "summary" des passenden Eintrags, NICHT in eigene Einträge.
  Typisch sind 1-6 Einträge pro Dokument.
- "title": konkret und selbsterklärend, z. B. "MRI Knie links: Innenmeniskusriss
  Hinterhorn" oder "Arthroskopie Knie links, Teilmeniskektomie medial" -
  nie nur "Diagnose" oder "Befund".

Regeln:
- Das Dokument kann deutsch, französisch oder italienisch sein. "title" und
  "summary" immer auf Deutsch; "quote" immer wörtlich in der Originalsprache.
- "quote": wörtliche Textstelle (ein bis zwei Sätze) aus dem Dokument, die die
  Angabe belegt. Nicht umformulieren, nichts kürzen oder ergänzen.
- "page": Blattzahl N aus der Markierung "=== Bl. N d. A. ===" der Fundstelle.
- "fact_date": ISO-Datum (JJJJ-MM-TT, JJJJ-MM oder JJJJ) des Ereignisses. Es muss
  in der zitierten Textstelle stehen; steht dort keines, nimm das Dokumentdatum;
  ist auch das unbekannt: null. Nie das Unfalldatum übernehmen, wenn das Dokument
  es nicht selbst nennt. Keine Daten aus relativen Angaben errechnen.
- "fact_date_end": Ende eines Zeitraums (Hospitalisation, Reha, Arbeitsunfähigkeit),
  wenn genannt; sonst null.
- "event_category": vorbefund | trauma (Unfallhergang) | diagnostik | op |
  konservativ | reha | arbeitsfaehigkeit | begutachtung | korrespondenz
- "causality": 'vorschaden' = vor dem Unfalltag dokumentiert;
  'unfallkausal' = Folge des Unfallereignisses; 'kombiniert' = Vorschaden +
  Unfallfolge; 'unklar' = nicht sicher zuordenbar; 'none' = ohne Bezug.
- "laterality": links | rechts | beidseits | na.

Dokumenttext:
{doc_text}
"""

COVER_PROMPT = """\
Die folgenden Seiten sind der Anfang einer Gutachterakte (Gutachtenauftrag,
Beweisbeschluss oder Anschreiben des Auftraggebers). Lies heraus:
- auftraggeber (Gericht / Versicherung), aktenzeichen (Geschäfts-/Aktenzahl),
  patient_name, patient_dob, accident_date (Unfall-/Ereignisdatum):
  jeweils {{"value": ..., "quote": wörtliche Textstelle}} oder null.
  Daten als ISO JJJJ-MM-TT.
- deadlines: Fristen (Abgabe des Gutachtens) und Termine (Untersuchung) mit
  wörtlicher Textstelle.
- questions: die Beweisfragen / der Fragenkatalog, jede Frage wörtlich und vollständig.
Nur was im Text steht. Fehlt etwas: null bzw. leere Liste.

Text:
{text}
"""

NARRATIVE_PROMPT = """\
Schreibe den Abschnitt „{section}“ eines orthopädischen Gutachtens.
Quelle sind AUSSCHLIESSLICH die folgenden belegten Einträge aus der Akte.

Regeln:
- Sachlicher Gutachtenstil, chronologisch, vollständige deutsche Sätze.
- Jeder Satz gibt in "refs" die Kennungen (z. B. "E3") der Einträge an, auf die er
  sich stützt. Kein Satz ohne Beleg.
- Nur Inhalte aus den Einträgen. Keine eigenen Wertungen, keine Aussagen zur
  Kausalität, keine Diagnosen, die nicht in den Einträgen stehen.
- Daten im Format TT.MM.JJJJ, nur Daten aus den Einträgen.
- Mehrere Einträge zum selben Ereignis in einem Satz zusammenfassen: pro
  Untersuchung, Eingriff oder Behandlungsphase ein bis zwei Sätze, keine
  Wiederholungen von Datum und Untersuchungsart.

Belegte Einträge:
{entries}
"""

BASIS_PROMPT = """\
Bereite für die/den Sachverständige/n die Entscheidungsgrundlage vor zu:
{topic}
Unfalldatum: {accident_date}

Du triffst KEINE Entscheidung und formulierst KEINE Schlussfolgerung. Du ordnest nur
die belegten Einträge den Gruppen zu:
- "fuer_unfall": Angaben, die für einen Zusammenhang mit dem Unfall sprechen
- "fuer_vorzustand": Angaben, die für einen Vorzustand / eine andere Ursache sprechen
- "offen": Unklarheiten, fehlende Angaben, Widersprüche
Jeder Punkt ist ein kurzer sachlicher Satz mit den Kennungen der Einträge in "refs".
Höchstens 12 Punkte insgesamt, die wichtigsten zuerst. Nur relevante Einträge;
nichts erfinden.

Belegte Einträge:
{entries}
"""
