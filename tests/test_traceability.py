# SPDX-License-Identifier: AGPL-3.0-or-later
"""Traceable, correctable workflow: Aktenauszug edits survive reruns, step states
show what is stale, the protocol lists every change. Fictitious data only."""
from gutachten.analysis.runner import run_analysis
from gutachten.cases import connect_case

from .test_analysis import FakeLLM, akte  # noqa: F401
from .test_api import client


def _tl(cid):
    return client.get(f"/api/cases/{cid}/timeline").json()


def _steps(cid):
    return {s["key"]: s for s in client.get(f"/api/cases/{cid}/steps").json()["steps"]}


def test_edit_exclude_restore_and_manual_entry(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks", "draft"],
                 llm_factory=FakeLLM)
    e = _tl(akte)[0]
    r = client.patch(f"/api/cases/{akte}/timeline/{e['id']}",
                     json={"title": "Korrigierter Titel (Testfall)"}).json()
    assert r["edited"] == 1 and r["original_json"] and r["reviewed"] == 1
    # the rerun keeps the correction and does not add the event a second time
    run_analysis(akte, ["timeline"], llm_factory=FakeLLM)
    rows = _tl(akte)
    assert [x["title"] for x in rows].count("Korrigierter Titel (Testfall)") == 1
    assert not any(x["title"] == e["title"] for x in rows)
    r = client.post(f"/api/cases/{akte}/timeline/{e['id']}/restore").json()
    assert r["title"] == e["title"] and r["edited"] == 0
    # exclusion: kept for the record, not used downstream
    x = _tl(akte)[1]
    client.post(f"/api/cases/{akte}/timeline/{x['id']}/exclude", json={"value": True})
    from gutachten.analysis.drafting import _entries

    c = connect_case(akte)
    assert x["id"] not in {d["id"] for d in _entries(c, akte)}
    c.close()
    # manual entry with and without page reference
    ok = client.post(f"/api/cases/{akte}/timeline", json={
        "entry_date": "01.02.2024", "title": "Telefonat Hausarzt (fiktiv)", "seq": 1})
    assert ok.status_code == 200
    m = next(t for t in _tl(akte) if t["id"] == ok.json()["id"])
    assert m["created_by"] == "user" and m["entry_date"] == "2024-02-01"
    assert m["citations"][0]["global_seq"] == 1
    assert client.post(f"/api/cases/{akte}/timeline", json={
        "entry_date": "kein Datum", "title": "x"}).status_code == 422
    assert client.delete(f"/api/cases/{akte}/timeline/{x['id']}").status_code == 400
    assert client.delete(f"/api/cases/{akte}/timeline/{m['id']}").status_code == 200


def test_manual_change_makes_downstream_stale(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline", "checks", "draft"],
                 llm_factory=FakeLLM)
    s = _steps(akte)
    assert s["gutachten"]["state"] != "veraltet" and s["auszug"]["state"] == "prüfen"
    e = _tl(akte)[0]
    client.post(f"/api/cases/{akte}/timeline/{e['id']}/reviewed", json={"value": True})
    assert _steps(akte)["gutachten"]["state"] != "veraltet"  # reviewing changes nothing
    client.patch(f"/api/cases/{akte}/timeline/{e['id']}", json={"summary": "ergänzt"})
    s = _steps(akte)
    assert s["hinweise"]["state"] == "veraltet" and s["gutachten"]["state"] == "veraltet"
    assert s["gutachten"]["recompute"] == ["checks", "checks_ki", "draft"]
    run_analysis(akte, ["checks", "draft"], llm_factory=FakeLLM)
    s = _steps(akte)
    assert s["gutachten"]["state"] != "veraltet" and s["hinweise"]["state"] != "veraltet"


def test_protocol_lists_user_and_model_actions(akte):  # noqa: F811
    run_analysis(akte, ["index", "extract", "timeline"], llm_factory=FakeLLM)
    e = _tl(akte)[0]
    client.patch(f"/api/cases/{akte}/timeline/{e['id']}", json={"title": "Neu (fiktiv)"})
    p = client.get(f"/api/cases/{akte}/protocol").json()
    assert any(r["wer"] == "Sachverständige/r" and r["aktion"] == "auszug_edited" for r in p)
    assert any(r["wer"] == "KI-Modell" for r in p)
    csv = client.get(f"/api/cases/{akte}/protocol.csv")
    assert csv.status_code == 200 and "auszug_edited" in csv.text


def test_refresh_runs_only_what_is_missing_or_stale(akte):  # noqa: F811
    from gutachten.analysis.steps import plan_refresh

    c = connect_case(akte)
    assert plan_refresh(c, akte, False) == ["index", "extract", "timeline", "checks",
                                            "checks_ki", "draft"]
    c.close()
    run_analysis(akte, ["index", "extract", "timeline", "checks", "checks_ki", "draft"],
                 llm_factory=FakeLLM)
    c = connect_case(akte)
    assert plan_refresh(c, akte, False) == []                    # all up to date
    assert plan_refresh(c, akte, True) == ["vorentwurf"]         # only what is missing
    c.close()
    e = _tl(akte)[0]
    client.patch(f"/api/cases/{akte}/timeline/{e['id']}", json={"summary": "geändert"})
    c = connect_case(akte)
    assert plan_refresh(c, akte, False) == ["checks", "checks_ki", "draft"]
    c.close()


def test_refresh_endpoint_reports_up_to_date(akte):  # noqa: F811
    run_analysis(akte, ["cover", "index", "extract", "timeline", "checks", "checks_ki",
                        "draft"], llm_factory=FakeLLM)
    r = client.post(f"/api/cases/{akte}/refresh?vorentwurf=false").json()
    assert r == {"up_to_date": True, "steps": []}
