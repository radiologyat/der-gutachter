# SPDX-License-Identifier: AGPL-3.0-or-later
"""Report templates per type of assignment and the deterministic section builders.

Source: KSVI Anhang IV (BSV, Stand 1.1.2025) — for IV specialist reports the nine
headings are mandatory and must be used verbatim ("Synonyme sind nicht erlaubt",
EKQMB Prüffrage A1). See docs/GUTACHTEN-ANFORDERUNGEN.md.

Everything here is built from data (case details, Akte, examination, structured
answers, diagnoses) without a language model. Missing input becomes a placeholder
"[… eintragen]" / "[Ihre Antwort]", which blocks approval of the section.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

from .. import config, icd10

# (key, heading, kind). kind: data | narrative | basis | questions | manual
TEMPLATES: dict[str, tuple[tuple[str, str, str], ...]] = {
    # IV: KSVI Anhang IV — headings verbatim, order fixed
    "iv": (
        ("ausgangslage", "1. Ausgangslage und Formelles", "data"),
        ("aktenauszug", "2. Aktenauszug", "data"),
        ("befragung", "3. Befragung", "data"),
        ("befund", "4. Befund", "data"),
        ("dritte", "5. Allfällige Angaben von Dritten", "manual"),
        ("med_beurteilung", "6. Medizinische Beurteilung", "data"),
        ("vm_beurteilung", "7. Versicherungsmedizinische Beurteilung (Prognose und Fähigkeiten)",
         "data"),
        ("fragen", "8. Aufführung und Beantwortung der Fragen", "questions"),
        ("beilagen", "9. Beilagen", "data"),
    ),
    # Unfallversicherung (UVG): same backbone, causality-centred assessment
    "uv": (
        ("ausgangslage", "1. Ausgangslage und Formelles", "data"),
        ("aktenauszug", "2. Aktenauszug", "data"),
        ("befragung", "3. Befragung", "data"),
        ("befund", "4. Befund", "data"),
        ("dritte", "5. Allfällige Angaben von Dritten", "manual"),
        ("med_beurteilung", "6. Medizinische Beurteilung", "data"),
        ("beurteilung", "7. Beurteilung des Zusammenhangs mit dem Ereignis", "basis"),
        ("fragen", "8. Beantwortung der Fragen", "questions"),
        ("beilagen", "9. Beilagen", "data"),
    ),
    # Haftpflicht / Gericht / sonstige Aufträge
    "allgemein": (
        ("ausgangslage", "1. Auftrag und Formelles", "data"),
        ("anamnese_aktenlage", "2. Anamnese nach Aktenlage", "narrative"),
        ("befragung", "3. Eigene Angaben der untersuchten Person", "data"),
        ("befund", "4. Untersuchungsbefund", "data"),
        ("zusatzbefunde", "5. Bildgebung und Zusatzbefunde", "narrative"),
        ("med_beurteilung", "6. Diagnosen", "data"),
        ("beurteilung", "7. Beurteilung", "basis"),
        ("fragen", "8. Beantwortung der Fragen", "questions"),
        ("beilagen", "9. Beilagen", "data"),
    ),
    # Österreich — Grundgerüst, NICHT gegen österreichische Vorgaben verifiziert
    # (Trennung Befund / Gutachten; MdE; im Zivilverfahren Schmerzperioden)
    "at": (
        ("ausgangslage", "1. Auftrag und Formelles", "data"),
        ("aktenauszug", "2. Aktenlage", "data"),
        ("befragung", "3. Anamnese (Angaben der untersuchten Person)", "data"),
        ("befund", "4. Befund", "data"),
        ("med_beurteilung", "5. Diagnosen", "data"),
        ("beurteilung", "6. Gutachten", "basis"),
        ("fragen", "7. Beantwortung der Fragen", "questions"),
        ("beilagen", "8. Beilagen", "data"),
    ),
}
TEMPLATE_FOR_CASE_TYPE = {"invaliditaet": "iv", "unfall": "uv"}

ANSWER = "[Ihre Antwort]"


def template_for(case: dict) -> str:
    if case.get("jurisdiction") == "AT":
        return "at"
    return TEMPLATE_FOR_CASE_TYPE.get(case.get("case_type") or "", "allgemein")


def de(iso: str | None) -> str:
    if not iso:
        return ""
    y, *rest = str(iso)[:10].split("-")
    return ".".join([*reversed(rest), y]) if rest else y


def _v(value, placeholder: str) -> str:
    """Value or a blocking placeholder."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return f"[{placeholder} eintragen]"
    return str(value)


def expert() -> dict:
    return config.load_settings().get("expert") or {}


# ------------------------------------------------------------------ 1. Ausgangslage

def build_ausgangslage(conn: sqlite3.Connection, case: dict, tpl: str) -> str:
    e = expert()
    ex_time = (f"{de(case.get('exam_date'))}, {case.get('exam_start')}–{case.get('exam_end')} Uhr"
               if case.get("exam_date") and case.get("exam_start") and case.get("exam_end")
               else None)
    qs = [dict(r) for r in conn.execute(
        "SELECT ord, text FROM questions WHERE case_id=? ORDER BY ord", (case["id"],))]
    docs = conn.execute("SELECT COUNT(*) FROM documents WHERE case_id=? AND excluded=0",
                        (case["id"],)).fetchone()[0]
    pages = conn.execute("SELECT COUNT(*) FROM pages WHERE case_id=?",
                         (case["id"],)).fetchone()[0]
    lines = [
        "### 1.1 Abwicklung des Gutachtensauftrages / Formelles",
        "",
        f"- **Auftraggeber:** {_v(case.get('auftraggeber'), 'Auftraggeber')}",
        f"- **Versicherte Person:** {_v(case.get('patient_name'), 'Name, Vorname')}"
        f", geb. {_v(de(case.get('patient_dob')), 'Geburtsdatum')}",
        f"- **Adresse:** {_v(case.get('patient_address'), 'Adresse')}",
    ]
    if tpl == "iv":
        lines.append(f"- **AHV-Nummer:** {_v(case.get('ahv_nr'), 'AHV-Nummer')}")
    lines += [
        f"- **Identitätsprüfung:** {_v(case.get('identity_check'), 'Art der Identitätsprüfung')}",
        f"- **Sachverständige/r:** {_v(e.get('name'), 'Name der/des Sachverständigen')}, "
        f"{_v(e.get('title'), 'Facharzttitel')}, {_v(e.get('address'), 'Praxisadresse')}",
        f"- **Auftragsdatum:** {_v(de(case.get('order_date')), 'Auftragsdatum')} · "
        f"**Eingang:** {_v(de(case.get('received_date')), 'Eingangsdatum')}",
        f"- **Exploration:** {_v(ex_time, 'Datum und Uhrzeit von–bis der Untersuchung')}",
        f"- **Dolmetscher:** {case.get('interpreter') or 'keiner'}",
        f"- **Fertigstellung:** {_v(de(case.get('completed_date')), 'Datum der Fertigstellung')}",
        "",
        "### 1.2 Anlass und Umstände der Begutachtung",
        "",
        # the country is evident to the client and the court — not stated in the report
        f"Ereignis/Anlass: {de(case.get('accident_date')) or '[Anlass eintragen]'}",
        "",
        "**Fragestellung:**" if qs else "**Fragestellung:** [Fragestellung eintragen]",
        *[f"{q['ord']}. {q['text']}" for q in qs],
        "",
        f"**Anforderungsprofil bisherige Tätigkeit:** "
        f"{_v(case.get('job_profile'), 'Anforderungsprofil der bisherigen Tätigkeit')}",
        "",
        "### 1.3 Übersicht der verwendeten Quellen",
        "",
        f"- Vom Auftraggeber zur Verfügung gestellte Akten: {docs} Dokumente, "
        f"{pages} Blatt (Verzeichnis unter Aktenauszug bzw. Beilagen)",
        "- Eigene Untersuchung und Befunde (siehe Befund)",
        "- Zusätzlich beigezogene Unterlagen und Untersuchungen: [ergänzen oder „keine“ eintragen]",
        "- Angaben von Drittpersonen: siehe Abschnitt Angaben von Dritten",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ 2. Aktenauszug

def build_aktenauszug(conn: sqlite3.Connection, case_id: str) -> str:
    """Chronological list: date — document (Bl.) — core statement (EKQMB C2:
    source, date and core statement of every piece of information)."""
    entries = [dict(r) for r in conn.execute(
        "SELECT * FROM timeline_entries WHERE case_id=? AND excluded=0 "
        "ORDER BY entry_date, sort", (case_id,))]
    if not entries:
        return "[Akte noch nicht ausgewertet — im Reiter „Register“ auswerten]"
    lines = ["Chronologisch, mit Quelle und Fundstelle (Bl. = Blatt der Akte).", ""]
    for e in entries:
        cites = json.loads(e["citations"] or "[]")
        docs = sorted({(c.get("doc_title") or "Dokument", c.get("global_seq")) for c in cites},
                      key=lambda x: x[1] or 0)
        src = "; ".join(f"{t} (Bl. {s})" for t, s in docs)
        span = de(e["entry_date"]) + (f"–{de(e['date_end'])}" if e.get("date_end") else "")
        summary = e["summary"] if e.get("summary") and e["summary"] != e["title"] else ""
        lines.append(f"- **{span}** — {e['title']}" + (f". {summary}" if summary else "")
                     + (f" — *{src}*" if src else ""))
    return "\n".join(lines)


# ------------------------------------------------------------------ 3. Befragung (manual)

BEFRAGUNG_HINT = {
    "iv": "### 3.1 Spontane Angaben der versicherten Person\n\n"
          "[Angaben der versicherten Person in indirekter Rede eintragen]\n\n"
          "### 3.2 Vertiefende Befragung\n\n"
          "- Jetziges Leiden: [eintragen]\n"
          "- Bisherige Behandlungen inkl. Medikamente: [eintragen]\n"
          "- Arbeitsbiografie und arbeitsbezogenes Beschwerdebild: [eintragen]\n"
          "- Soziale Anamnese und Tagesablauf: [eintragen]\n"
          "- Besprechung von Inkonsistenzen: [eintragen oder „keine“]",
}


def befragung_hint(tpl: str) -> str:
    return BEFRAGUNG_HINT.get(
        tpl, "[Angaben der untersuchten Person in indirekter Rede eintragen]")


# ------------------------------------------------------------------ 4. Befund (exam)

def _table(head: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head),
            *["| " + " | ".join(r) + " |" for r in rows], ""]


def build_befund(conn: sqlite3.Connection, case: dict) -> str:
    ex = json.loads(case.get("exam_json") or "{}")
    lines = []
    if case.get("interpreter") or ex.get("verhalten"):
        dolm = (f"mit Dolmetscher ({case['interpreter']})" if case.get("interpreter")
                else "ohne Dolmetscher")
        lines += ["### Verhalten und Verständigung", "",
                  ex.get("verhalten") or "[Verhaltensbeobachtung eintragen]",
                  f"Verständigung: {dolm}.", ""]
    lines += ["### Untersuchungsbefunde", ""]
    methode = ex.get("methode") or ("Bewegungsumfang nach der Neutral-0-Methode "
                                    "(Goniometer), Umfangmasse mit Massband.")
    lines.append(f"*Methode:* {methode}")
    lines.append("")
    for key, label in (("allgemein", "Allgemeinbefund"), ("gang", "Gangbild")):
        if ex.get(key):
            lines += [f"**{label}:** {ex[key]}", ""]
    rom = [r for r in ex.get("rom", []) if r.get("rechts") or r.get("links")]
    if rom:
        lines += ["**Bewegungsumfang (Neutral-0-Methode, Grad):**", ""]
        lines += _table(["Gelenk", "Bewegung", "rechts", "links"],
                        [[r.get("gelenk", ""), r.get("bewegung", ""), r.get("rechts") or "–",
                          r.get("links") or "–"] for r in rom])
    um = [r for r in ex.get("umfang", []) if r.get("rechts") or r.get("links")]
    if um:
        lines += ["**Umfangmasse (cm):**", ""]
        lines += _table(["Messstelle", "rechts", "links"],
                        [[r.get("stelle", ""), str(r.get("rechts") or "–"),
                          str(r.get("links") or "–")] for r in um])
    tests = [r for r in ex.get("tests", []) if r.get("rechts") or r.get("links")]
    if tests:
        lines += ["**Klinische Tests:**", ""]
        lines += _table(["Test", "rechts", "links"],
                        [[r.get("test", ""), r.get("rechts") or "–", r.get("links") or "–"]
                         for r in tests])
    for key, label in (("neuro", "Neurostatus"), ("weitere", "Weitere Befunde")):
        if ex.get(key):
            lines += [f"**{label}:** {ex[key]}", ""]
    if not (rom or um or tests or ex.get("allgemein")):
        lines += ["[Untersuchungsbefund im Reiter „Untersuchung“ erfassen]", ""]
    imaging = [dict(r) for r in conn.execute(
        """SELECT entry_date, title, citations FROM timeline_entries
           WHERE case_id=? AND excluded=0 AND category='diagnostik'
           ORDER BY entry_date""", (case["id"],))]
    lines += ["### Zusatzbefunde", ""]
    if imaging:
        lines += ["Aus der Akte (Bildgebung und weitere Untersuchungen):", ""]
        for i in imaging:
            seqs = sorted({c.get("global_seq") for c in json.loads(i["citations"] or "[]")
                           if c.get("global_seq")})
            lines.append(f"- {de(i['entry_date'])}: {i['title']}"
                         + (f" (Bl. {', '.join(map(str, seqs))})" if seqs else ""))
    lines.append(ex.get("zusatz") or "- Eigene Zusatzuntersuchungen: [eintragen oder „keine“]")
    return "\n".join(lines).rstrip()


# ------------------------------------------------------------------ 6. Medizinische Beurteilung

def build_diagnoses(conn: sqlite3.Connection, case_id: str) -> tuple[str, list[str]]:
    """Diagnoses with ICD-10 (EKQMB D2: coding is mandatory)."""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM diagnoses WHERE case_id=? ORDER BY ord, id", (case_id,))]
    if not rows:
        return ("[Diagnosen im Reiter „Untersuchung“ erfassen — Vorschläge aus der Akte "
                "stehen dort bereit]"), []
    lines, problems = [], []
    groups = ((1, "Diagnosen mit Auswirkung auf die Arbeitsfähigkeit"),
              (0, "Diagnosen ohne Auswirkung auf die Arbeitsfähigkeit"),
              (None, "Diagnosen"))
    n = 0
    for flag, head in groups:
        items = [r for r in rows if r["af_relevant"] == flag]
        if not items:
            continue
        if any(r["af_relevant"] is not None for r in rows):
            lines += [f"**{head}:**", ""]
        for r in items:
            n += 1
            code = r["icd10"] if icd10.valid_format(r["icd10"]) else None
            side = {"links": " links", "rechts": " rechts", "beidseits": " beidseits"}.get(
                r.get("laterality") or "", "")
            lines.append(f"{n}. {r['text']}{side}"
                         + (f", seit {de(r['since'])}" if r.get("since") else "")
                         + (f" (ICD-10 {code})" if code else " [ICD-10-Code eintragen]"))
            if not code:
                problems.append(r["text"])
        lines.append("")
    lines.append("*Diagnosesystem: ICD-10-GM.*")
    return "\n".join(lines), problems


def build_med_beurteilung(conn: sqlite3.Connection, case: dict, tpl: str) -> str:
    diag, _ = build_diagnoses(conn, case["id"])
    if tpl in ("allgemein", "at"):
        return diag
    findings = [dict(r) for r in conn.execute(
        "SELECT type, claim, source_a, source_b FROM findings WHERE case_id=? AND status!="
        "'rejected' ORDER BY severity='high' DESC, id", (case["id"],))]
    af_prior = [dict(r) for r in conn.execute(
        """SELECT f.fact_date, f.title, p.global_seq, d.title AS doc FROM facts f
           JOIN pages p ON p.id=f.page_id JOIN documents d ON d.id=f.document_id
           WHERE f.case_id=? AND f.verified=1 AND d.excluded=0
             AND f.event_category='arbeitsfaehigkeit' ORDER BY f.fact_date""", (case["id"],))]
    lines = ["### 6.1 Zusammenfassung", "",
             "[Zusammenfassung der persönlichen, beruflichen und gesundheitlichen Entwicklung "
             "eintragen]", "", "### 6.2 Beurteilung von Konsistenz und Plausibilität", ""]
    if findings or af_prior:
        lines += ["*Aus der Aktenprüfung (zur Diskussion, keine Beurteilung):*", ""]
        for f in findings:
            seqs = [json.loads(x)["global_seq"] for x in (f["source_a"], f["source_b"]) if x]
            lines.append(f"- {f['claim']} (Bl. {', '.join(map(str, seqs))})")
        if af_prior:
            lines += ["", "*Frühere Einschätzungen der Arbeitsfähigkeit (EKQMB D3):*", ""]
            lines += [f"- {de(a['fact_date'])}: {a['title']} — {a['doc']} (Bl. {a['global_seq']})"
                      for a in af_prior]
        lines.append("")
    lines += ["[Stellungnahme zu Konsistenz und Plausibilität der Beschwerden, Befunde und "
              "Vorberichte eintragen]", "", "### 6.3 Diagnosen", "", diag]
    return "\n".join(lines)


# ------------------------------------------------------------------ 7. VM-Beurteilung

PROFILE_LABEL = {
    "heben_selten_kg": "Heben/Tragen selten (kg)",
    "heben_gelegentlich_kg": "Heben/Tragen gelegentlich (kg)",
    "heben_haeufig_kg": "Heben/Tragen häufig (kg)",
    "haltung": "Arbeitshaltung", "stehen_gehen_max": "Stehen/Gehen am Stück",
    "sitzen_max": "Sitzen am Stück", "knien": "Knien/Hocken", "leitern": "Leitern/Gerüste",
    "ueberkopf": "Überkopfarbeiten", "gelaende": "Gehen auf unebenem Gelände",
    "treppen": "Treppensteigen", "weitere": "Weitere Einschränkungen",
}


def render_profile(profile: dict) -> list[str]:
    rows = [[label, str(profile[k])] for k, label in PROFILE_LABEL.items()
            if profile.get(k) not in (None, "")]
    return _table(["Belastung", "zumutbar"], rows) if rows else []


def build_vm_beurteilung(conn: sqlite3.Connection, case: dict) -> str:
    ans = json.loads(case.get("answers_json") or "{}")
    therapy = [dict(r) for r in conn.execute(
        """SELECT entry_date, date_end, title FROM timeline_entries WHERE case_id=? AND excluded=0
           AND category IN ('op','konservativ','reha') ORDER BY entry_date""", (case["id"],))]
    lines = ["### 7.1 Bisheriger Verlauf von Behandlungen und Heilungschancen", ""]
    if therapy:
        lines += ["*Behandlungen laut Akte:*", ""]
        lines += [f"- {de(t['entry_date'])}" + (f"–{de(t['date_end'])}" if t["date_end"] else "")
                  + f": {t['title']}" for t in therapy]
        lines.append("")
    lines += [ans.get("therapieverlauf") or "[Beurteilung des Therapieverlaufs, ob Behandlungen "
              "angemessen und ausgeschöpft sind, Prognose eintragen]", "",
              "### 7.2 Würdigung von Fähigkeiten, Ressourcen und Belastungen", "",
              ans.get("faehigkeiten") or "[Funktions- und Fähigkeitsstörungen, Ressourcen und "
              "Belastungen eintragen]", ""]
    prof = render_profile(ans.get("profil") or {})
    if prof:
        lines += ["**Belastbarkeitsprofil:**", "", *prof]
    return "\n".join(lines).rstrip()


# ------------------------------------------------------------------ 8. Fragen

def _pct(v) -> str | None:
    return None if v in (None, "") else f"{v} %"


def _af_block(a: dict, label: str) -> list[str]:
    af = a.get("af_pct")
    auf = None if af in (None, "") else 100 - float(af)
    auf_s = None if auf is None else (f"{auf:g} %")
    out = [f"**Arbeitsfähigkeit bzw. Arbeitsunfähigkeit {label}**", ""]
    if label == "in angepasster Tätigkeit":
        out += ["*Welche Merkmale müsste eine der Behinderung optimal angepasste Tätigkeit "
                "aufweisen?*", a.get("merkmale") or ANSWER, ""]
    stunden = (f"{a['praesenz_h']} Stunden pro Tag" if a.get("praesenz_h") not in (None, "")
               else ANSWER)
    out += [
        "*Wie viele Stunden pro Tag ist eine Anwesenheit möglich?*", stunden, "",
        "*Besteht während dieser Anwesenheitszeit eine Einschränkung der Leistung? Wenn ja, in "
        "welchem Umfang und warum?*",
        (("Nein." if not float(a["leistung_einschraenkung_pct"]) else
          f"Ja, {a['leistung_einschraenkung_pct']} %: {a.get('einschraenkung_grund') or ANSWER}")
         if a.get("leistung_einschraenkung_pct") not in (None, "") else ANSWER), "",
        "*Arbeitsfähigkeit bzw. Arbeitsunfähigkeit insgesamt, bezogen auf ein 100 %-Pensum:*",
        (f"Arbeitsfähigkeit {_pct(af)}, Arbeitsunfähigkeit {auf_s}." if af not in (None, "")
         else ANSWER), "",
        "*Zeitlicher Verlauf der Entwicklung dieser Arbeitsfähigkeit:*",
        a.get("verlauf") or ANSWER, "",
    ]
    return out


# Beweismass Sozialversicherung: überwiegende Wahrscheinlichkeit (FMH/SAMW 9.3)
UV_KAUSAL = {
    "ueberwiegend_wahrscheinlich":
        "Der Zusammenhang mit dem Ereignis ist mit überwiegender Wahrscheinlichkeit gegeben.",
    "moeglich":
        "Der Zusammenhang mit dem Ereignis ist möglich, aber nicht überwiegend wahrscheinlich.",
    "unwahrscheinlich": "Ein Zusammenhang mit dem Ereignis ist unwahrscheinlich.",
}


def build_at_questions(case: dict) -> str:
    """Austria (unverified skeleton): MdE in % (Sozialversicherung) and, in civil
    proceedings, pain periods. Only rendered where entered."""
    at = (json.loads(case.get("answers_json") or "{}")).get("at") or {}
    lines = []
    if at.get("mde_pct") not in (None, ""):
        lines += ["*Minderung der Erwerbsfähigkeit (MdE):*",
                  f"{at['mde_pct']} %" + (f", ab {de(at.get('mde_ab'))}" if at.get("mde_ab")
                                         else "") + (f". {at['mde_begruendung']}"
                                                     if at.get("mde_begruendung") else "."), ""]
    sp = [(k, at.get(k)) for k in ("schmerzen_stark", "schmerzen_mittel", "schmerzen_leicht")]
    if any(v not in (None, "") for _, v in sp):
        lines += ["*Schmerzperioden (komprimiert):*",
                  ", ".join(f"{label} {v} Tage" for (_, v), label in
                            zip(sp, ("starke", "mittelstarke", "leichte"), strict=True)
                            if v not in (None, "")) + ".", ""]
    return "\n".join(lines)


def build_standard_questions(case: dict, tpl: str) -> str:
    if tpl == "at":
        return build_at_questions(case)
    ans = json.loads(case.get("answers_json") or "{}")
    lines: list[str] = []
    if tpl == "uv":
        uv = ans.get("uv") or {}
        k = UV_KAUSAL.get(uv.get("kausalitaet") or "")
        lines += ["**Natürliche Kausalität**", "",
                  "*Sind die festgestellten Gesundheitsschäden natürlich kausal auf das Ereignis "
                  "zurückzuführen?*",
                  (f"{k} {uv.get('kausalitaet_begruendung') or ANSWER}" if k else ANSWER), "",
                  "*Status quo sine / ante:*",
                  {"erreicht": f"Erreicht ab {de(uv.get('status_quo_datum')) or ANSWER}.",
                   "nicht_erreicht": "Nicht erreicht.",
                   "nicht_beurteilbar": "Nicht beurteilbar: "
                                        + (uv.get("status_quo_begruendung") or ANSWER)}.get(
                      uv.get("status_quo") or "", ANSWER), "",
                  "*Ist von der Fortsetzung der ärztlichen Behandlung noch eine namhafte "
                  "Besserung zu erwarten?*",
                  {"ja": "Ja.", "nein": f"Nein, Behandlungsabschluss ab "
                                        f"{de(uv.get('behandlungsabschluss_datum')) or ANSWER}."}
                  .get(uv.get("behandlungsabschluss") or "", ANSWER), "",
                  "*Integritätsschaden:*",
                  (f"{uv['integritaet_pct']} % "
                   f"({uv.get('integritaet_grundlage') or 'Grundlage eintragen'}). "
                   f"{uv.get('integritaet_begruendung') or ''}".strip()
                   if uv.get("integritaet_pct") not in (None, "") else ANSWER), ""]
    lines += _af_block(ans.get("bisherige") or {}, "in der bisherigen Tätigkeit")
    lines += _af_block(ans.get("angepasst") or {}, "in angepasster Tätigkeit")
    prof = render_profile(ans.get("profil") or {})
    if prof:
        lines += ["*Belastbarkeitsprofil der angepassten Tätigkeit:*", "", *prof]
    m = ans.get("massnahmen") or {}
    lines += ["**Medizinische Massnahmen und Therapien mit Auswirkungen auf die "
              "Arbeitsfähigkeit**", "",
              "*Kann die Arbeitsfähigkeit durch medizinische Massnahmen relevant verbessert "
              "werden?*"]
    if m.get("verbesserbar") == "nein":
        lines.append(f"Nein. {m.get('begruendung') or ANSWER}")
    elif m.get("verbesserbar") == "ja":
        lines += [f"Ja. Optionen: {m.get('optionen') or ANSWER}",
                  f"Behandlungsdauer bis zum Erfolg: {m.get('dauer') or ANSWER}",
                  f"Evidenz und erwarteter Erfolg: {m.get('evidenz') or ANSWER}",
                  f"Medizinische Gründe/Risiken dagegen: {m.get('risiken') or ANSWER}"]
    else:
        lines.append(ANSWER)
    return "\n".join(lines)


# ------------------------------------------------------------------ 9. Beilagen

def build_beilagen(conn: sqlite3.Connection, case: dict, tpl: str) -> str:
    e = expert()
    today = de(case.get("completed_date")) or de(dt.date.today().isoformat())
    lines = ["- Aktenverzeichnis mit Blattzahlen (Fundstellenverzeichnis, siehe Anhang)",
             "- Zusätzlich beschaffte Dokumente: [eintragen oder „keine“]", "",
             "**Erklärung zur Unabhängigkeit, Unbefangenheit und Objektivität**", "",
             "Die/der Unterzeichnende bestätigt hiermit, den Auftrag frei von "
             "Interessenbindungen, unparteiisch und in voller Unabhängigkeit ausgeführt und in "
             "der Argumentation und bei der Beantwortung der Fragen die allgemein anerkannten "
             "medizinischen Erkenntnisse und die versicherungsmedizinischen "
             "Rahmenbedingungen berücksichtigt zu haben.", ""]
    if tpl in ("iv", "uv"):
        lines += ["**Bestätigung der Übermittlung der Tonaufnahme**", "",
                  "Die/der Unterzeichnende bestätigt die ordnungsgemässe Übermittlung der "
                  "Tonaufnahme entsprechend den Vorgaben des Auftraggebers "
                  "[oder: Verzicht der versicherten Person liegt vor — zutreffendes eintragen].",
                  ""]
    lines += ["**Hinweis zu technischen Hilfsmitteln**", "",
              "Zur Ordnung der Akten (Texterkennung, Register, chronologischer Aktenauszug mit "
              "Fundstellen) wurde eine lokal betriebene Software als Hilfsmittel eingesetzt. "
              "Befragung, Untersuchung, Beurteilung und Beantwortung der Fragen erfolgten "
              "persönlich durch die/den Unterzeichnende/n.", "",
              f"{e.get('name') or '[Name eintragen]'}, "
              f"{e.get('title') or '[Facharzttitel eintragen]'} — {today}"]
    return "\n".join(lines)
