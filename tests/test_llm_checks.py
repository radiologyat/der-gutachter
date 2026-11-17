# SPDX-License-Identifier: AGPL-3.0-or-later
"""KI-Prüfung: content issues with verified sources, no judgement, decisions kept.
Fictitious data only."""
import json

from gutachten.analysis.runner import run_analysis
from gutachten.cases import connect_case

from .test_analysis import FakeLLM, akte  # noqa: F401


def _ki(cid):
    c = connect_case(cid)
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM findings WHERE created_by='ki' ORDER BY id")]
    audit = [r[0] for r in c.execute(
        "SELECT detail FROM audit_log WHERE action='checks_ki'")]
    c.close()
    return rows, audit


def test_only_verified_issues_are_kept(akte):  # noqa: F811
    res = run_analysis(akte, ["index", "extract", "timeline", "checks", "checks_ki"],
                       llm_factory=FakeLLM)
    assert res["checks_ki"] == {"findings": 1, "dropped": 3}
    rows, audit = _ki(akte)
    f = rows[0]
    assert f["type"] == "ki_vorschaden_abgrenzung" and f["status"] == "open"
    assert f["claim"] == "Dieselbe Region wurde vor dem Ereignis bereits behandelt."
    assert json.loads(f["source_a"])["global_seq"] and "KI-Hinweis" in f["explanation"]
    assert "unbekannte Einträge" in audit[-1] and "nicht in den Belegen" in audit[-1]
    assert "enthält ein Urteil" in audit[-1]


def test_rule_checks_keep_ki_findings_and_decisions_survive(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks", "checks_ki"],
                 llm_factory=FakeLLM)
    rows, _ = _ki(akte)
    c = connect_case(akte)
    c.execute("UPDATE findings SET status='rejected' WHERE id=?", (rows[0]["id"],))
    c.commit()
    c.close()
    run_analysis(akte, ["checks"], llm_factory=FakeLLM)       # rules do not touch KI rows
    assert len(_ki(akte)[0]) == 1
    run_analysis(akte, ["checks_ki"], llm_factory=FakeLLM)    # rejected one not raised again
    rows, _ = _ki(akte)
    assert [r["status"] for r in rows] == ["rejected"]


def test_ki_findings_appear_in_decision_basis(akte):  # noqa: F811
    from .test_drafting import DraftFake

    run_analysis(akte, ["index", "extract", "timeline", "checks", "checks_ki", "draft"],
                 llm_factory=DraftFake)
    c = connect_case(akte)
    b = c.execute("SELECT content_md FROM draft_sections WHERE section_key IN "
                  "('beurteilung','fragen')").fetchall()
    c.close()
    assert any("KI-Hinweis aus der Prüfung: Dieselbe Region" in r[0] for r in b)
