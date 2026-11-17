# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 4: report templates per assignment type, structured inputs (formal
details, examination, standard answers, ICD-10 diagnoses), approval gate, export.
All case content is fictitious (see tests/TESTDATA.md)."""
import json
import re

import pytest
from docx import Document

from gutachten import config
from gutachten.analysis.drafting import (
    EXPERT_JUDGEMENT,
    WARN,
    ApprovalBlocked,
    approval_problems,
    generate_draft,
    reset_section,
    update_section,
)
from gutachten.analysis.report_sections import TEMPLATES
from gutachten.analysis.runner import run_analysis
from gutachten.cases import connect_case, update_case
from gutachten.export import export_docx

from .test_analysis import FakeLLM, akte  # noqa: F401  (fixture)

KSVI_HEADINGS = [
    "1. Ausgangslage und Formelles", "2. Aktenauszug", "3. Befragung", "4. Befund",
    "5. Allfällige Angaben von Dritten", "6. Medizinische Beurteilung",
    "7. Versicherungsmedizinische Beurteilung (Prognose und Fähigkeiten)",
    "8. Aufführung und Beantwortung der Fragen", "9. Beilagen",
]


class DraftFake(FakeLLM):
    """Adds drafting answers; lies on purpose to exercise the checks."""

    def _refs(self, prompt):
        return re.findall(r"^\[(E\d+)\]", prompt, re.M)

    def _draft_narrative(self, prompt):
        refs = self._refs(prompt)
        return {"sentences": [
            {"text": "Erstvorstellung mit belegten Befunden.", "refs": refs[:1]},
            {"text": "Weiterer Verlauf wie dokumentiert.", "refs": refs[1:2]},
            {"text": "Eine Operation fand statt.", "refs": ["E99"]},            # unknown ref
            {"text": "Am 01.01.2019 erfolgte eine Kontrolle.", "refs": refs[:1]},  # bad date
        ]}

    def _draft_basis(self, prompt):
        refs = self._refs(prompt)
        return {"points": [
            {"group": "fuer_vorzustand", "text": "Gonarthrose vorbekannt.", "refs": refs[:1]},
            {"group": "fuer_unfall", "text": "Frische Läsion nach dem Ereignis.",
             "refs": refs[-1:]},
            {"group": "offen", "text": "Unklare Angabe ohne Beleg.", "refs": []},
        ]}


def _secs(conn, case_id):
    return {r["section_key"]: dict(r) for r in conn.execute(
        "SELECT * FROM draft_sections WHERE case_id=? ORDER BY ord", (case_id,))}


@pytest.fixture()
def analysed(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    conn = connect_case(akte)
    conn.execute("INSERT INTO questions (case_id, ord, text) VALUES (?, 1, ?)",
                 (akte, "Welche Gesundheitsschäden liegen vor?"))
    conn.commit()
    yield akte, conn
    conn.close()


def _set(case_id, **fields):
    update_case(case_id, fields)


# ------------------------------------------------------------------ templates

def test_iv_template_uses_ksvi_headings_verbatim(analysed):
    case_id, conn = analysed
    _set(case_id, case_type="invaliditaet")
    res = generate_draft(conn, case_id, DraftFake())
    assert res["template"] == "iv" and res["failed"] == []
    assert [s["title"] for s in _secs(conn, case_id).values()] == KSVI_HEADINGS
    assert [t for _, t, _ in TEMPLATES["iv"]] == KSVI_HEADINGS


def test_template_follows_case_type_and_switch_cleans_up(analysed):
    case_id, conn = analysed
    _set(case_id, case_type="haftpflicht")
    generate_draft(conn, case_id, DraftFake())
    assert "anamnese_aktenlage" in _secs(conn, case_id)
    update_section(conn, case_id, "befragung", content="Eigene Notizen der Gutachterin.")
    _set(case_id, case_type="invaliditaet")
    generate_draft(conn, case_id, DraftFake())
    secs = _secs(conn, case_id)
    assert "anamnese_aktenlage" not in secs and "aktenauszug" in secs  # old one removed
    assert secs["befragung"]["content_md"] == "Eigene Notizen der Gutachterin."  # kept


# ------------------------------------------------------------------ 1. formal details

def test_formal_details_and_expert_profile(analysed, monkeypatch, tmp_path):
    case_id, conn = analysed
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "s.json")
    _set(case_id, case_type="invaliditaet")
    generate_draft(conn, case_id, None)
    a = _secs(conn, case_id)["ausgangslage"]["content_md"]
    for missing in ("AHV-Nummer", "Facharzttitel", "Datum und Uhrzeit von–bis"):
        assert f"[{missing}" in a
    assert approval_problems(a)
    config.save_settings({"expert": {"name": "Dr. med. Erika Beispiel", "title": "FMH "
                                     "Orthopädische Chirurgie", "address": "Musterweg 1"}})
    _set(case_id, patient_name="Max Muster", patient_dob="1961-03-12", ahv_nr="756.1234.5678.97",
         patient_address="Musterstrasse 1, 8000 Musterstadt", identity_check="ID-Karte",
         order_date="2026-09-01", received_date="2026-09-03", exam_date="2026-10-14",
         exam_start="09:00", exam_end="11:15", completed_date="2026-11-01",
         job_profile="Bauarbeiter, schwere körperliche Tätigkeit")
    generate_draft(conn, case_id, None)
    a = _secs(conn, case_id)["ausgangslage"]["content_md"]
    assert "14.10.2026, 09:00–11:15 Uhr" in a and "756.1234.5678.97" in a
    assert "Dr. med. Erika Beispiel, FMH Orthopädische Chirurgie" in a
    assert "Welche Gesundheitsschäden liegen vor?" in a
    assert "[ergänzen oder „keine“ eintragen]" in a  # still one conscious decision left


# ------------------------------------------------------------------ 3. examination

EXAM = {
    "allgemein": "Normalgewichtig, guter Allgemeinzustand.",
    "rom": [{"gelenk": "Knie", "bewegung": "Extension/Flexion", "rechts": "0-0-140",
             "links": "0-5-110"},
            {"gelenk": "Hüfte", "bewegung": "Extension/Flexion", "rechts": "", "links": ""}],
    "umfang": [{"stelle": "15 cm oberhalb Kniegelenkspalt", "rechts": 48, "links": 46}],
    "tests": [{"test": "Lachman", "rechts": "negativ", "links": "negativ"}],
    "neuro": "Sensibilität und Motorik intakt.",
}


def test_befund_generated_from_structured_exam(analysed):
    case_id, conn = analysed
    from .test_api import client

    assert client.put(f"/api/cases/{case_id}/exam", json=EXAM).status_code == 200
    assert client.get(f"/api/cases/{case_id}/exam").json()["neuro"] == EXAM["neuro"]
    generate_draft(conn, case_id, None)
    b = _secs(conn, case_id)["befund"]["content_md"]
    assert "Neutral-0-Methode" in b  # EKQMB C3: method named
    assert "| Knie | Extension/Flexion | 0-0-140 | 0-5-110 |" in b
    assert "Hüfte" not in b  # empty rows omitted
    assert "| 15 cm oberhalb Kniegelenkspalt | 48 | 46 |" in b
    assert "Sensibilität und Motorik intakt." in b


# ------------------------------------------------------------------ 4. standard questions

def test_iv_standard_questions_with_both_values(analysed):
    case_id, conn = analysed
    _set(case_id, case_type="invaliditaet")
    generate_draft(conn, case_id, None)
    f = _secs(conn, case_id)["fragen"]["content_md"]
    assert "Wie viele Stunden pro Tag" in f and "[Ihre Antwort]" in f
    assert "### Fallspezifische Fragen" in f and "Welche Gesundheitsschäden liegen vor?" in f
    conn.execute("UPDATE cases SET answers_json=?", (json.dumps({
        "bisherige": {"praesenz_h": 8, "leistung_einschraenkung_pct": 30,
                      "einschraenkung_grund": "vermehrte Pausen", "af_pct": 70,
                      "verlauf": "seit 01.03.2024 unverändert"},
        "angepasst": {"merkmale": "wechselbelastend, ohne Knien", "praesenz_h": 8.5,
                      "leistung_einschraenkung_pct": 0, "af_pct": 100, "verlauf": "ab sofort"},
        "profil": {"heben_selten_kg": 15, "knien": "nicht zumutbar"},
        "massnahmen": {"verbesserbar": "nein", "begruendung": "Endzustand erreicht."},
    }),))
    conn.commit()
    generate_draft(conn, case_id, None)
    f = _secs(conn, case_id)["fragen"]["content_md"]
    assert "Arbeitsfähigkeit 70 %, Arbeitsunfähigkeit 30 %." in f  # both values (KSVI)
    assert "Ja, 30 %: vermehrte Pausen" in f
    assert "Arbeitsfähigkeit 100 %, Arbeitsunfähigkeit 0 %." in f
    assert "| Knien/Hocken | nicht zumutbar |" in f
    assert "Nein. Endzustand erreicht." in f
    # standard part complete; only the case-specific answer remains open
    assert f.count("[Ihre Antwort]") == 1


def test_uv_questions_cover_causality_and_integrity(analysed):
    case_id, conn = analysed
    conn.execute("UPDATE cases SET answers_json=?", (json.dumps({"uv": {
        "kausalitaet": "ueberwiegend_wahrscheinlich", "kausalitaet_begruendung": "Typischer "
        "Mechanismus.", "status_quo": "erreicht", "status_quo_datum": "2024-06-30",
        "behandlungsabschluss": "nein", "behandlungsabschluss_datum": "2024-09-01",
        "integritaet_pct": 10, "integritaet_grundlage": "Suva-Tabelle 5"}}),))
    conn.commit()
    generate_draft(conn, case_id, None)
    f = _secs(conn, case_id)["fragen"]["content_md"]
    assert ("Der Zusammenhang mit dem Ereignis ist mit überwiegender Wahrscheinlichkeit "
            "gegeben. Typischer Mechanismus.") in f
    assert "Erreicht ab 30.06.2024." in f and "Behandlungsabschluss ab 01.09.2024" in f
    assert "10 % (Suva-Tabelle 5)." in f


# ------------------------------------------------------------------ 5. diagnoses / ICD-10

def test_diagnoses_with_icd_and_gate(analysed):
    from .test_api import client

    case_id, conn = analysed
    sugg = client.get(f"/api/cases/{case_id}/diagnoses/suggestions").json()
    assert any("Gonarthrose" in s["title"] for s in sugg)  # from the Akte, with source
    assert all("global_seq" in s for s in sugg)
    bad = client.post(f"/api/cases/{case_id}/diagnoses", json={"text": "X", "icd10": "12345"})
    assert bad.status_code == 422
    client.post(f"/api/cases/{case_id}/diagnoses",
                json={"text": "Mediale Gonarthrose", "icd10": "m171", "laterality": "links",
                      "af_relevant": 1, "source": "akte"})
    did = client.post(f"/api/cases/{case_id}/diagnoses",
                      json={"text": "Status nach Meniskusteilresektion", "af_relevant": 0}
                      ).json()["id"]
    generate_draft(conn, case_id, None)
    d = _secs(conn, case_id)["med_beurteilung"]["content_md"]
    assert "Mediale Gonarthrose links (ICD-10 M17.1)" in d  # normalised "m171"
    assert "Status nach Meniskusteilresektion [ICD-10-Code eintragen]" in d
    assert "Diagnosen mit Auswirkung auf die Arbeitsfähigkeit" in d
    assert any("ICD-10-Code" in p for p in approval_problems(d))
    client.put(f"/api/cases/{case_id}/diagnoses/{did}",
               json={"text": "Status nach Meniskusteilresektion", "icd10": "Z98.8",
                     "af_relevant": 0})
    generate_draft(conn, case_id, None)
    d = _secs(conn, case_id)["med_beurteilung"]["content_md"]
    assert "[ICD-10-Code eintragen]" not in d
    assert client.get("/api/icd10?q=menisk").json()["results"]


# ------------------------------------------------------------------ AI parts, gate, export

def test_narrative_and_basis_keep_their_safeguards(analysed):
    case_id, conn = analysed
    _set(case_id, case_type="haftpflicht")
    generate_draft(conn, case_id, DraftFake())
    s = _secs(conn, case_id)
    a = s["anamnese_aktenlage"]
    assert "Erstvorstellung mit belegten Befunden. (Bl." in a["content_md"]
    assert a["content_md"].count(WARN) == 2
    b = s["beurteilung"]["content_md"]
    assert "keine Beurteilung" in b and EXPERT_JUDGEMENT in b and WARN in b


def test_edited_sections_survive_regeneration_until_reset(analysed):
    case_id, conn = analysed
    generate_draft(conn, case_id, None)
    update_section(conn, case_id, "aktenauszug", content="Von Hand gekürzter Aktenauszug.")
    res = generate_draft(conn, case_id, None)
    assert "aktenauszug" in res["skipped"]
    reset_section(conn, case_id, "aktenauszug")
    generate_draft(conn, case_id, None)
    assert _secs(conn, case_id)["aktenauszug"]["content_md"].startswith("Chronologisch")
    with pytest.raises(ApprovalBlocked, match="Platzhalter"):
        update_section(conn, case_id, "befragung", status="approved")


def test_export_tables_and_draft_marker(analysed):
    case_id, conn = analysed
    conn.execute("UPDATE cases SET exam_json=?", (json.dumps(EXAM),))
    conn.commit()
    generate_draft(conn, case_id, None)
    path, final = export_docx(case_id)
    d = Document(str(path))
    assert not final and "ENTWURF" in d.sections[0].header.paragraphs[0].text
    knee = [t for t in d.tables if t.rows[0].cells[0].text == "Gelenk"]
    assert knee and knee[0].rows[1].cells[2].text == "0-0-140"
    for r in conn.execute("SELECT section_key FROM draft_sections").fetchall():
        update_section(conn, case_id, r["section_key"], content="Freigegebener Text.",
                       status="approved")
    path, final = export_docx(case_id)
    assert final and "ENTWURF" not in Document(str(path)).sections[0].header.paragraphs[0].text


def test_expert_profile_api(monkeypatch, tmp_path):
    from .test_api import client

    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "s.json")
    assert client.get("/api/settings/expert").json()["name"] == ""
    client.put("/api/settings/expert", json={"name": "Dr. A", "title": "FMH", "address": "X"})
    assert client.get("/api/settings/expert").json()["title"] == "FMH"
    assert client.patch(f"/api/cases/{_any_case()}", json={"ahv_nr": "123"}).status_code == 422


def _any_case():
    from .test_api import client

    return client.post("/api/cases", json={"title": "Formal"}).json()["id"]


def test_headings_follow_template_even_when_section_is_not_regenerated(analysed):
    """A section the model would rebuild keeps its content without a model, but
    its heading must still be the current template's (outdated heading = defect)."""
    case_id, conn = analysed
    generate_draft(conn, case_id, DraftFake())          # uv template, with model
    conn.execute("UPDATE draft_sections SET title='Beurteilung' WHERE section_key='beurteilung'")
    conn.commit()
    generate_draft(conn, case_id, None)                 # no model available
    t = _secs(conn, case_id)["beurteilung"]["title"]
    assert t == "7. Beurteilung des Zusammenhangs mit dem Ereignis"


def test_austria_gets_its_own_skeleton(analysed):
    case_id, conn = analysed
    _set(case_id, jurisdiction="AT")
    conn.execute("UPDATE cases SET answers_json=?", (json.dumps(
        {"at": {"mde_pct": 20, "schmerzen_stark": 3, "schmerzen_leicht": 28}}),))
    conn.commit()
    res = generate_draft(conn, case_id, None)
    assert res["template"] == "at"
    assert [t for _, t, _ in TEMPLATES["at"]][5] == "6. Gutachten"
    titles = [s["title"] for s in _secs(conn, case_id).values()]
    assert titles[1] == "2. Aktenlage"  # "6. Gutachten" needs the model (basis)
    f = _secs(conn, case_id)["fragen"]["content_md"]
    assert "20 %" in f and "starke 3 Tage, leichte 28 Tage" in f
    assert "AHV" not in _secs(conn, case_id)["ausgangslage"]["content_md"]


def test_typography():
    from gutachten.export import NBSP, typeset

    t = typeset('Laut Bericht "frischer Riss" - siehe Bl. 4 d. A., z. B. 3-5 Tage, 20 % AF.')
    assert "„frischer Riss“" in t and " – siehe" in t
    assert f"Bl.{NBSP}4" in t and f"d.{NBSP}A." in t and f"z.{NBSP}B." in t
    assert "3–5" in t and f"20{NBSP}%" in t
    # Neutral-0 measurements keep their hyphens
    assert typeset("Extension/Flexion 0-0-140, Rotation 20-0-30") == \
        "Extension/Flexion 0-0-140, Rotation 20-0-30"


def test_report_title_and_subtitle():
    from gutachten.export import report_subtitle, report_title

    assert report_title("uv", {}) == "Orthopädisch-traumatologisches Gutachten"
    assert report_title("iv", {"report_title": "Orthopädisches Gutachten"}) == \
        "Orthopädisches Gutachten"
    assert report_subtitle("iv", {}).startswith("Monodisziplinäres Gutachten")
    assert report_subtitle("allgemein", {"auftraggeber": "Bezirksgericht Muster"}) == \
        "Gerichtsgutachten"
    assert report_subtitle("allgemein", {"auftraggeber": "Haftpflicht AG"}) is None
