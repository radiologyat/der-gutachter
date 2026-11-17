# SPDX-License-Identifier: AGPL-3.0-or-later
"""KI-Vorentwurf: judgement placeholders get cited, marked proposals; interview,
findings and formal details are never generated. Fictitious data only."""
import json
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn

from gutachten.analysis import common
from gutachten.analysis.drafting import approval_problems, generate_draft
from gutachten.analysis.proposals import KI_OPEN, accept_proposals, run_proposals
from gutachten.analysis.runner import run_analysis
from gutachten.cases import connect_case
from gutachten.export import export_docx

from .test_analysis import (
    ARZTBRIEF_1,
    ARZTBRIEF_2,
    AUFTRAG,
    MRI_1,
    OP,
    FakeLLM,
    _pdf,
    akte,  # noqa: F401  (fixture)
)
from .test_drafting import DraftFake
from .test_pipeline import _wait


class ProposalFake(DraftFake):
    def _vorentwurf(self, prompt):
        refs = re.findall(r"^\[(E\d+)\]", prompt, re.M)
        return {"sentences": [
            {"text": "Laut Akte besteht ein vorbestehender Knorpelschaden.", "refs": refs[:1]},
            {"text": "Am 03.03.2015 wurde bereits operiert.", "refs": refs[:1]},  # invented date
            {"text": "Die Arbeitsfähigkeit beträgt 80 %.", "refs": []},          # number, no source
            {"text": "Die abschliessende Beurteilung erfordert die persönliche Untersuchung.",
             "refs": []},                                                          # allowed
        ]}

    def _vorentwurf_antwort(self, prompt):
        refs = re.findall(r"^\[(E\d+)\]", prompt, re.M)
        q = prompt.split("<<<", 1)[1].split(">>>", 1)[0].strip().split("\n")[-1]
        return {"empfehlung": {"text": f"Zu „{q[:40]}“ ist der Befund überwiegend "
                                       "wahrscheinlich ereignisbedingt.", "refs": refs[:1]},
                "begruendung": [
                    {"text": "Laut Akte besteht ein vorbestehender Knorpelschaden.",
                     "refs": refs[:1]},
                    {"text": "Am 03.03.2015 wurde bereits operiert.", "refs": refs[:1]},
                    {"text": "Die Leistungen wurden sistiert, was gegen Kausalität spricht.",
                     "refs": refs[:1]},
                    {"text": "Die Beweglichkeit ist gemäß Bericht gemindert.", "refs": refs[:1]}],
                "zu_pruefen": ["Beweglichkeit Knie (Neutral-0-Methode)",
                               "Röntgen vom 01.01.2020 nachfordern"]}


def _secs(c, cid):
    return {r["section_key"]: dict(r) for r in c.execute(
        "SELECT * FROM draft_sections WHERE case_id=? ORDER BY ord", (cid,))}


def test_proposals_fill_only_judgement_placeholders(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    c.execute("INSERT INTO questions (case_id, ord, text) VALUES (?, 1, 'Unfallkausal?')", (akte,))
    c.commit()
    generate_draft(c, akte, ProposalFake())
    before = _secs(c, akte)
    res = run_proposals(c, akte, ProposalFake())
    s = _secs(c, akte)
    assert res["proposals"] >= 4
    for key in ("med_beurteilung", "beurteilung", "fragen"):
        assert KI_OPEN in s[key]["content_md"], key
    # never generated: formal details, interview, examination, attachments
    for key in ("ausgangslage", "befragung", "befund", "dritte", "beilagen"):
        assert s[key]["content_md"] == before[key]["content_md"], key
    full = s["beurteilung"]["content_md"]
    b = full[full.index(KI_OPEN):]
    assert "Empfehlung: " in b and "Begründung: Laut Akte besteht ein vorbestehender " \
        "Knorpelschaden. (Bl." in b and "[durch die" not in b
    # unverifiable dates and insurer arguments are dropped, not printed
    assert "03.03.2015" not in b and "sistiert" not in b and "⚠" not in b
    assert "Zu prüfen: Beweglichkeit Knie (Neutral-0-Methode)." in b and "01.01.2020" not in b
    assert "gemäss Bericht" in b and "ß" not in b  # Swiss spelling
    m = " ".join(re.findall(r"⟦KI⟧.*?⟦/KI⟧", s["med_beurteilung"]["content_md"], re.S))
    assert "Die Arbeitsfähigkeit beträgt 80 %" not in m and "⚠" not in m
    w = " ".join(json.loads(s["beurteilung"]["warnings"]))
    assert "verworfen" in w and "Rechts-/Versicherungsargument" in w
    assert any("KI-Vorschl" in p for p in approval_problems(full))
    c.close()


def test_accept_removes_markers_and_protects_text(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    generate_draft(c, akte, ProposalFake())
    run_proposals(c, akte, ProposalFake())
    n = accept_proposals(c, akte, "med_beurteilung")
    row = _secs(c, akte)["med_beurteilung"]
    assert n >= 1 and KI_OPEN not in row["content_md"] and row["user_edited"] == 1
    assert row["status"] == "reviewed"
    assert "med_beurteilung" in generate_draft(c, akte, ProposalFake())["skipped"]
    c.close()


def test_export_marks_vorentwurf(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    generate_draft(c, akte, ProposalFake())
    run_proposals(c, akte, ProposalFake())
    c.close()
    path, final = export_docx(akte)
    d = Document(str(path))
    assert not final and "VORENTWURF" in d.sections[0].header.paragraphs[0].text
    # black-and-white: grey shading + label instead of a coloured marker
    shaded = [r for p in d.paragraphs for r in p.runs
              if r._element.rPr is not None and r._element.rPr.find(qn("w:shd")) is not None]
    assert any(r.text == "[KI-Vorschlag, ungeprüft] " for r in shaded)
    assert not any(r.font.highlight_color == WD_COLOR_INDEX.YELLOW
                   for p in d.paragraphs for r in p.runs)


def test_one_click_folder_to_vorentwurf(tmp_path, monkeypatch):
    from .test_api import client

    monkeypatch.setattr(common, "get_llm", ProposalFake)
    monkeypatch.setattr(common, "_extract_model_path", lambda: Path("model.gguf"))
    cid = client.post("/api/cases", json={"title": "Vorentwurf"}).json()["id"]
    files = [("files", (n, _pdf(tmp_path / n, p).read_bytes(), "application/pdf"))
             for n, p in (("01.pdf", [AUFTRAG]), ("02.pdf", [ARZTBRIEF_1, ARZTBRIEF_2]),
                          ("03.pdf", [MRI_1]), ("04.pdf", [OP]))]
    client.post(f"/api/cases/{cid}/files", files=files)
    job = _wait(client.post(f"/api/cases/{cid}/intake?vorentwurf=true").json()["job_id"])
    assert job["status"] == "done", job
    assert job["result"]["vorentwurf"]["proposals"] > 0
    r = client.get(f"/api/cases/{cid}/export.docx")
    assert r.status_code == 200
    assert client.post(f"/api/cases/{cid}/drafts/fragen/accept-proposals").json()["accepted"] > 0


def test_question_context_excludes_previous_proposals():
    from gutachten.analysis.proposals import _question_context

    before = ("**Natürliche Kausalität**\n\n*Ist es kausal?*\n⟦KI⟧ Alte Antwort 1. ⟦/KI⟧\n\n"
              "*Integritätsschaden:*\n")
    ctx = _question_context(before)
    assert "Integritätsschaden" in ctx and "Alte Antwort" not in ctx


def test_accident_date_and_question_numbers_are_not_flagged():
    from gutachten.analysis.proposals import _render

    by_ref = {"E1": {"entry_date": "2024-03-18", "date_end": None,
                     "cites": [{"global_seq": 4, "quote": "MRI vom 18.03.2024"}]}}
    w: list = []
    out = _render([{"text": "Riss konsistent mit dem Unfall vom 12.03.2024.", "refs": ["E1"]},
                   {"text": "Die AF bezogen auf ein 100 %-Pensum ist offen.", "refs": []}],
                  by_ref, w, context="*Arbeitsfähigkeit, bezogen auf ein 100 %-Pensum:*",
                  accident="2024-03-12")
    assert "⚠" not in out and w == []


def test_exam_dependent_questions_get_provisional_recommendation(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    c.execute("UPDATE cases SET case_type='invaliditaet'")
    c.commit()
    generate_draft(c, akte, ProposalFake())
    run_proposals(c, akte, ProposalFake())
    f = _secs(c, akte)["fragen"]["content_md"]
    c.close()
    i = f.find("*Wie viele Stunden pro Tag")
    nxt = f[i:f.index("⟦/KI⟧", i)]
    assert f"{KI_OPEN} Empfehlung: Vorläufig nach Aktenlage, vorbehaltlich der " \
        "persönlichen Untersuchung:" in nxt
    assert "Zu prüfen:" in nxt
    assert any("KI-Vorschl" in p for p in approval_problems(f))


def test_repeated_sentences_dropped_within_section():
    from gutachten.analysis.proposals import _render
    seen: list = []
    one = [{"text": "Die Akte ist zu diesem Punkt unvollständig.", "refs": []}]
    reworded = [{"text": "Zu diesem Punkt ist die Akte unvollständig.", "refs": []}]
    assert _render(one, {}, [], seen=seen) == "Die Akte ist zu diesem Punkt unvollständig."
    assert _render(reworded, {}, [], seen=seen) == ""


def test_case_questions_refer_to_basis_and_flag_adequacy(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    c.execute("UPDATE cases SET case_type='unfall'")
    c.execute("INSERT INTO questions (case_id, ord, text) VALUES (?, 1, "
              "'Besteht ein natürlicher und adäquater Kausalzusammenhang?')", (akte,))
    c.commit()
    generate_draft(c, akte, ProposalFake())
    f = _secs(c, akte)["fragen"]["content_md"]
    c.close()
    q = f[f.index("**Frage 1:**"):]
    assert "siehe Ziff. 7" in q and "Für einen Zusammenhang" not in q
    assert "Die Adäquanz ist eine Rechtsfrage" in q


def test_insurer_entries_are_not_medical_evidence(akte):  # noqa: F811
    from gutachten.analysis.drafting import _entries
    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    c.execute("INSERT INTO timeline_entries (case_id, entry_date, category, title) "
              "VALUES (?, '2024-05-20', 'begutachtung', 'Verfügung Versicherer')", (akte,))
    c.commit()
    titles = [e["title"] for e in _entries(c, akte, medical_only=True)]
    assert "Verfügung Versicherer" not in titles
    assert "Verfügung Versicherer" in [e["title"] for e in _entries(c, akte)]
    c.close()


def test_repeated_recommendation_is_retried_then_dropped(akte):  # noqa: F811
    class Copycat(ProposalFake):
        def _vorentwurf_antwort(self, prompt):
            out = super()._vorentwurf_antwort(prompt)
            out["empfehlung"]["text"] = "Der Meniskusriss ist überwiegend wahrscheinlich " \
                "natürlich kausal auf das Ereignis zurückzuführen."
            return out

    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    c.execute("UPDATE cases SET case_type='unfall'")
    c.commit()
    generate_draft(c, akte, Copycat())
    run_proposals(c, akte, Copycat())
    f = _secs(c, akte)["fragen"]
    c.close()
    # given once in Ziff. 7 (case-wide memory) — the answers refer to it
    assert f["content_md"].count("Meniskusriss ist überwiegend wahrscheinlich") == 0
    assert "Siehe Empfehlung zu „Ärztliche Beurteilung:“ (oben)." in f["content_md"]
    assert "wiederholte frühere Antwort" in f["warnings"]


def test_absolute_statements_and_internal_ids_removed():
    from gutachten.analysis.proposals import _render

    by_ref = {"E1": {"entry_date": "2024-03-18", "date_end": None,
                     "cites": [{"global_seq": 4, "quote": "MRI vom 18.03.2024"}]}}
    w: list = []
    out = _render([
        {"text": "Der Riss ist irreversibel.", "refs": ["E1"]},
        {"text": "Der Sturz hat den Meniskusriss verursacht.", "refs": ["E1"]},
        {"text": "Der Vorzustand ist durch die Aktenbelege E1 und E2 gesichert.", "refs": ["E1"]},
    ], by_ref, w)
    assert "irreversibel" not in out and "verursacht" not in out
    assert "E1" not in out and "durch die Aktenbelege gesichert. (Bl. 4 d. A.)" in out
    assert sum("absolute Aussage" in x for x in w) == 2


def test_check_items_lose_internal_ids_and_lasting_prognosis_dropped():
    from gutachten.analysis.proposals import _render, _render_answer

    by_ref = {"E1": {"entry_date": "2024-03-18", "date_end": None,
                     "cites": [{"global_seq": 4, "quote": "MRI vom 18.03.2024"}]}}
    w: list = []
    out = _render_answer({
        "empfehlung": {"text": "Der Riss ist überwiegend wahrscheinlich ereignisbedingt.",
                       "refs": ["E1"]},
        "begruendung": [{"text": "Es braucht eine dauerhafte Schonung.", "refs": ["E1"]}],
        "zu_pruefen": ["Stabilität nach der Lungenembolie (E5)", "VKB-Veränderung (E7, E8)"]},
        by_ref, w, "", None, [], False)
    assert "E5" not in out and "E7" not in out and "dauerhafte" not in out
    assert "Zu prüfen: Stabilität nach der Lungenembolie; VKB-Veränderung." in out
    assert _render([{"text": "Dauerhafter Schaden.", "refs": ["E1"]}], by_ref, w) == ""


def test_status_quo_before_event_detected():
    from gutachten.analysis.proposals import _before_event

    acc = "2019-12-19"
    assert _before_event("Der status quo sine ist bereits vor dem Unfall erreicht worden.", acc)
    assert _before_event("Der status quo sine ist per 30.04.2019 erreicht.", acc)
    assert not _before_event("Der status quo sine ist per 30.04.2020 erreicht.", acc)
    assert _before_event("Der Status quo sine wird voraussichtlich ab voraussichtlich "
                         "09.05.2019 erreicht.", acc)
    assert not _before_event("Noch nicht erreicht; Röntgen vom 14.09.2018 zeigt Arthrose.", acc)


def test_recommendations_are_shared_across_sections(akte):  # noqa: F811
    """Ziff. 7 and the answers see each other's recommendations."""
    seen_prompts = []

    class Spy(ProposalFake):
        def _vorentwurf_antwort(self, prompt):
            seen_prompts.append(prompt)
            return super()._vorentwurf_antwort(prompt)

    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    c.execute("UPDATE cases SET case_type='unfall'")
    c.commit()
    generate_draft(c, akte, Spy())
    run_proposals(c, akte, Spy())
    c.close()
    first_in_fragen = next(p for p in seen_prompts if "Natürliche Kausalität" in p)
    assert "Ärztliche Beurteilung" in first_in_fragen.split("Bereits beantwortete")[1][:600]


def test_persisting_is_not_suspension():
    from gutachten.analysis.drafting import NON_MEDICAL_ARG

    assert not NON_MEDICAL_ARG.search("Persistierender Erguss, die Beschwerden persistieren.")
    assert NON_MEDICAL_ARG.search("Die Leistungen wurden sistiert.")
    assert NON_MEDICAL_ARG.search("Sistierung der Taggelder.")


def _answer(emp, refs, occ=None, why=None):
    return {"empfehlung": {"text": emp, "refs": refs}, "begruendung": why or [],
            "zu_pruefen": [],
            "gelegenheitsursache": occ or {"fuer_vorzustand": [], "fuer_ereignis": []}}


def test_trigger_on_prior_damage_needs_occasional_cause_weighing():
    from gutachten.analysis.proposals import _answer_problem

    by_ref = {"E1": {"entry_date": "2024-04-08", "date_end": None,
                     "cites": [{"global_seq": 4, "quote": "Sturz 08.04.2024"}]}}
    ctx = "**Ärztliche Beurteilung:**"
    bad = _answer("Das Syndrom ist überwiegend wahrscheinlich kausal auf den Sturz "
                  "zurückzuführen, da er als Auslöser bei bekannter Stenose wirkte.", ["E1"])
    problem, retry = _answer_problem(bad, bad["empfehlung"]["text"], None, ctx, "2024-04-08",
                                     by_ref, "Ärztliche Beurteilung")
    assert problem == "Gelegenheitsursache nicht geprüft" and "gelegenheitsursache" in retry
    weighed = _answer(bad["empfehlung"]["text"], ["E1"], {
        "fuer_vorzustand": [{"text": "Die Stenose war hochgradig.", "refs": ["E1"]}],
        "fuer_ereignis": [{"text": "Sofortige Ausfälle nach dem Sturz.", "refs": ["E1"]}]})
    assert _answer_problem(weighed, weighed["empfehlung"]["text"], None, ctx, "2024-04-08",
                           by_ref, "x")[0] is None
    # not a causality claim -> no weighing required
    ok = _answer("Das Syndrom ist überwiegend wahrscheinlich nicht unfallkausal.", ["E1"])
    assert _answer_problem(ok, ok["empfehlung"]["text"], None, ctx, "2024-04-08",
                           by_ref, "x")[0] is None


def test_unsupported_recommendation_is_retried():
    from gutachten.analysis.proposals import _answer_problem

    by_ref = {"E1": {"entry_date": "2024-03-18", "date_end": None,
                     "cites": [{"global_seq": 4, "quote": "MRI vom 18.03.2024"}]}}
    a = _answer("Der Status quo sine ist per 02.06.2024 noch nicht erreicht.", ["E1"])
    problem, retry = _answer_problem(a, a["empfehlung"]["text"], None, "*Status quo sine:*",
                                     "2024-03-02", by_ref, "Status quo")
    assert problem == "Empfehlung verworfen" and "nicht in den Belegen" in retry


def test_occasional_cause_weighing_is_rendered():
    from gutachten.analysis.proposals import _render_answer

    by_ref = {"E1": {"entry_date": "2024-04-08", "date_end": None,
                     "cites": [{"global_seq": 4, "quote": "Sturz"}]}}
    out = _answer("Nicht abschliessend beurteilbar.", [], {
        "fuer_vorzustand": [{"text": "Hochgradige Stenose seit Jahren.", "refs": ["E1"]}],
        "fuer_ereignis": [{"text": "Ausfälle unmittelbar nach dem Sturz.", "refs": ["E1"]}]})
    t = _render_answer(out, by_ref, [], "Ist der Schaden kausal?", None, [], False)
    assert ("Abwägung Gelegenheitsursache — für den Vorzustand spricht: Hochgradige Stenose "
            "seit Jahren. (Bl. 4") in t
    assert "Für das Ereignis als wesentliche Ursache spricht: Ausfälle unmittelbar" in t
    # not for questions without causality (work capacity)
    t = _render_answer(out, by_ref, [], "Wie viele Stunden pro Tag?", None, [], False)
    assert "Abwägung" not in t


def test_model_artefacts_are_removed():
    from gutachten.analysis.proposals import _clean

    assert _clean("lange bestehend refs.") == "lange bestehend."
    assert _clean("am Segment C3/4 (refs:.") == "am Segment C3/4."
    assert _clean("spricht dagegen (refs: E1, E2).") == "spricht dagegen."
    assert _clean("während [] ein Trauma ([], []) vorlag.") == "während ein Trauma vorlag."
    assert _clean("Die Präferenzen (Bl. 5) bleiben.") == "Die Präferenzen (Bl. 5) bleiben."


def test_causal_polarity_and_one_sided_weighing():
    from gutachten.analysis.proposals import _answer_problem, _polarity

    assert _polarity("Der Riss ist überwiegend wahrscheinlich kausal auf den Sturz "
                     "zurückzuführen.") == 1
    assert _polarity("Die Schäden sind überwiegend wahrscheinlich nicht natürlich kausal "
                     "auf das Ereignis zurückzuführen.") == -1
    assert _polarity("Nicht abschliessend beurteilbar.") == 0
    by_ref = {"E1": {"entry_date": "2024-04-08", "date_end": None,
                     "cites": [{"global_seq": 4, "quote": "Sturz"}]}}
    emp = ("Das Syndrom ist überwiegend wahrscheinlich kausal auf den Sturz zurückzuführen, "
           "da er Auslöser bei bekannter Stenose war.")
    one_sided = _answer(emp, ["E1"], {"fuer_vorzustand": [], "fuer_ereignis": [
        {"text": "Sofortige Ausfälle.", "refs": ["E1"]}]})
    assert _answer_problem(one_sided, emp, None, "**Ärztliche Beurteilung:**", "2024-04-08",
                           by_ref, "x")[0] == "Gelegenheitsursache nicht geprüft"


def test_contradicting_causal_recommendations_are_flagged(akte):  # noqa: F811
    """Ziff. 7 says causal, the answer says not causal: both kept, marked, approval
    blocked — the programme does not pick a side."""
    class Flip(ProposalFake):
        n = 0

        def _vorentwurf_antwort(self, prompt):
            out = super()._vorentwurf_antwort(prompt)
            Flip.n += 1
            out["empfehlung"]["text"] = (
                "Der Schaden ist überwiegend wahrscheinlich kausal auf das Ereignis "
                "zurückzuführen." if Flip.n == 1 else
                "Der Schaden ist überwiegend wahrscheinlich nicht natürlich kausal auf "
                "das Ereignis zurückzuführen, Befund degenerativ.")
            return out

    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    c.execute("UPDATE cases SET case_type='unfall'")
    c.commit()
    generate_draft(c, akte, Flip())
    run_proposals(c, akte, Flip())
    f = _secs(c, akte)["fragen"]
    c.close()
    assert "⚠ Widerspricht der Kausalitäts-Empfehlung zu „Ärztliche Beurteilung:“" \
        in f["content_md"]
    assert any("⚠" in p for p in approval_problems(f["content_md"]))


def test_dates_do_not_hide_causal_claims():
    from gutachten.analysis.proposals import _polarity

    assert _polarity("Die Verschlimmerung ist überwiegend wahrscheinlich auf den Sturz vom "
                     "19.12.2019 zurückzuführen.") == 1
    assert _polarity("Die Schäden sind überwiegend wahrscheinlich nicht kausal auf das "
                     "Ereignis vom 19.12.2019 zurückzuführen.") == -1


def test_weighing_without_valid_sources_counts_as_missing():
    from gutachten.analysis.proposals import _answer_problem

    by_ref = {"E1": {"entry_date": "2024-04-08", "date_end": None,
                     "cites": [{"global_seq": 4, "quote": "Sturz"}]}}
    emp = ("Das Syndrom ist überwiegend wahrscheinlich auf den Sturz vom 08.04.2024 "
           "zurückzuführen, da er Auslöser bei bekannter Stenose war.")
    a = _answer(emp, ["E1"], {"fuer_vorzustand": [{"text": "Stenose seit 1997.", "refs": ["E99"]}],
                              "fuer_ereignis": [{"text": "Sofortige Ausfälle.", "refs": ["E1"]}]})
    assert _answer_problem(a, emp, None, "**Ärztliche Beurteilung:**", "2024-04-08",
                           by_ref, "x")[0] == "Gelegenheitsursache nicht geprüft"


def test_clinic_statement_is_medical_insurer_ruling_is_not(akte):  # noqa: F811
    from gutachten.analysis.drafting import _entries

    run_analysis(akte, ["index", "extract", "timeline"], llm_factory=FakeLLM)
    c = connect_case(akte)
    fact, doc = c.execute("SELECT id, document_id FROM facts WHERE document_id IS NOT NULL "
                          "LIMIT 1").fetchone()
    cite = json.dumps([{"fact_id": fact, "global_seq": 1}])
    for title in ("Stellungnahme Klinik (fiktiv)", "Verfügung Versicherer (fiktiv)"):
        c.execute("INSERT INTO timeline_entries (case_id, entry_date, category, title, "
                  "citations) VALUES (?, '2024-06-02', 'begutachtung', ?, ?)",
                  (akte, title, cite))
    c.execute("UPDATE documents SET doc_type='arztbrief' WHERE id=?", (doc,))
    c.commit()
    titles = [e["title"] for e in _entries(c, akte, medical_only=True)]
    assert "Stellungnahme Klinik (fiktiv)" in titles
    c.execute("UPDATE documents SET doc_type='versicherung' WHERE id=?", (doc,))
    c.commit()
    titles = [e["title"] for e in _entries(c, akte, medical_only=True)]
    assert "Verfügung Versicherer (fiktiv)" not in titles
    c.close()
