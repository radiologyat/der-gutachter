# SPDX-License-Identifier: AGPL-3.0-or-later
"""Interview guide from the Akte, treatment gaps, Befragung section, indirect speech.
All case content is fictitious (see tests/TESTDATA.md)."""
import json
import re

from gutachten.analysis.checks import run_checks
from gutachten.analysis.drafting import generate_draft
from gutachten.analysis.interview import build_guide, render_befragung, to_indirect
from gutachten.analysis.runner import run_analysis
from gutachten.cases import connect_case

from .test_analysis import FakeLLM, akte  # noqa: F401  (fixture)
from .test_checks import accident_docs, conn, doc, fact, findings  # noqa: F401


class GuideFake(FakeLLM):
    def _interview_guide(self, prompt):
        refs = re.findall(r"^\[(E\d+)\]", prompt, re.M)
        return {"fragen": [
            {"frage": "Wann genau haben die Beschwerden begonnen?", "grund": "Beginn unklar.",
             "refs": refs[:1]},
            {"frage": "Erfundene Frage ohne Beleg?", "grund": "—", "refs": []},
        ]}

    def _indirect_speech(self, prompt):
        notes = prompt.rsplit("Notizen:\n", 1)[1].strip()
        if "18 Monate" in notes:  # lies: changes a number
            return {"text": "Die versicherte Person gibt an, sie habe seit 8 Monaten Schmerzen."}
        return {"text": "Die versicherte Person gibt an, sie habe seit drei Wochen Schmerzen "
                        "im linken Knie."}


def test_treatment_gap_is_a_finding(conn, case_id):  # noqa: F811
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    fact(conn, case_id, 2, "2023-10-20", "MRI Knie links", cat="diagnostik")
    fact(conn, case_id, 2, "2024-06-01", "Wiedervorstellung Knie links", cat="konservativ")
    run_checks(conn, case_id)
    gap = [f for f in findings(conn) if f["type"] == "coverage_gap"]
    assert len(gap) == 1 and "2023-10-20" in gap[0]["claim"] and gap[0]["severity"] == "low"


def test_guide_turns_findings_into_cited_questions(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks"], llm_factory=FakeLLM)
    c = connect_case(akte)
    c.execute("UPDATE cases SET accident_date='2023-10-09'")
    c.execute("INSERT INTO questions (case_id, ord, text) VALUES (?, 1, 'Unfallkausal?')",
              (akte,))
    c.commit()
    run_checks(c, akte)
    guide = build_guide(c, akte)
    origins = {g["origin"] for g in guide}
    assert {"standard", "finding", "beweisfrage"} <= origins
    pre = next(g for g in guide if g["origin"] == "finding" and "vor dem Ereignis" in g["question"])
    assert pre["sources"] and pre["sources"][0]["global_seq"] == 2   # Bl. of the Vorbefund
    assert pre["reason"].startswith("Vorbefund")
    guide_llm = build_guide(c, akte, GuideFake())
    llm_q = [g for g in guide_llm if g["origin"] == "llm"]
    assert [g["question"] for g in llm_q] == ["Wann genau haben die Beschwerden begonnen?"]
    assert llm_q[0]["sources"]          # cited; the unsourced question was dropped
    c.close()


def test_answers_become_the_befragung_section(akte):  # noqa: F811
    c = connect_case(akte)
    c.execute("UPDATE cases SET case_type='invaliditaet', interview_json=?", (json.dumps({
        "spontan": "Die versicherte Person gibt an, das Knie schmerze täglich.",
        "answers": {"arbeit": "Sie arbeite seit dem Ereignis 50 %.", "alltag": ""},
        "topics": {"arbeit": "Arbeit", "alltag": "Tagesablauf und Alltag"}}),))
    c.commit()
    generate_draft(c, akte, None)
    b = c.execute("SELECT content_md FROM draft_sections WHERE section_key='befragung'"
                  ).fetchone()[0]
    c.close()
    assert "### 3.1 Spontane Angaben der versicherten Person" in b
    assert "**Arbeit:** Sie arbeite seit dem Ereignis 50 %." in b
    assert "Tagesablauf" not in b       # unanswered topics are left out
    assert render_befragung({}, {}, "iv") is None


def test_indirect_speech_flags_changed_numbers(akte):  # noqa: F811
    c = connect_case(akte)
    ok = to_indirect(c, akte, GuideFake(), "Schmerzen seit drei Wochen, linkes Knie.")
    assert ok["text"].startswith("Die versicherte Person gibt an") and not ok["changed_facts"]
    bad = to_indirect(c, akte, GuideFake(), "Schmerzen seit 18 Monaten.")
    assert bad["changed_facts"] and "weichen ab" in bad["warning"]
    logged = c.execute("SELECT COUNT(*) FROM llm_calls WHERE stage='indirect_speech'"
                       ).fetchone()[0]
    c.close()
    assert logged == 2   # every call in the audit trail


def test_interview_api(akte):  # noqa: F811
    from .test_api import client

    assert client.get(f"/api/cases/{akte}/interview").json() == {}
    client.put(f"/api/cases/{akte}/interview", json={"spontan": "x", "answers": {}})
    assert client.get(f"/api/cases/{akte}/interview").json()["spontan"] == "x"
    g = client.get(f"/api/cases/{akte}/interview/guide").json()
    assert any(q["id"] == "jetziges_leiden" for q in g)
