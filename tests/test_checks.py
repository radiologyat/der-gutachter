# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 3 rules on hand-built documents/facts (deterministic, no LLM)."""
import json

import pytest

from gutachten.analysis.checks import region_of, run_checks
from gutachten.analysis.timeline import build_timeline
from gutachten.cases import connect_case

ACCIDENT = "2023-10-09"


@pytest.fixture()
def conn(case_id):
    c = connect_case(case_id)
    c.execute("UPDATE cases SET accident_date=?, patient_dob=NULL", (ACCIDENT,))
    c.execute("INSERT INTO sources (id, case_id, filename, sha256) VALUES (1, ?, 'x', 'h')",
              (case_id,))
    for seq in range(1, 9):
        c.execute("INSERT INTO pages (id, case_id, source_id, page_no, global_seq)"
                  " VALUES (?, ?, 1, ?, ?)", (seq, case_id, seq, seq))
    c.commit()
    yield c
    c.close()


def doc(c, case_id, did, name="Max Muster", dob="1961-03-12", title=None):
    c.execute("INSERT INTO documents (id, case_id, title, start_seq, end_seq, patient_name,"
              " patient_dob) VALUES (?,?,?,?,?,?,?)",
              (did, case_id, title or f"Dok {did}", did, did, name, dob))


def fact(c, case_id, did, date, title, cat="diagnostik", side="links", caus="unklar",
         region="Knie"):
    c.execute("INSERT INTO facts (case_id, document_id, page_id, fact_date, event_category,"
              " causality, laterality, body_region, title, summary, quote, verified)"
              " VALUES (?,?,?,?,?,?,?,?,?,?,?,1)",
              (case_id, did, did, date, cat, caus, side, region, title, title, title))


def findings(c):
    return [dict(r) for r in c.execute("SELECT * FROM findings ORDER BY id")]


def accident_docs(c, case_id):
    doc(c, case_id, 1, title="Notfall")
    fact(c, case_id, 1, ACCIDENT, "Sturz, Distorsion Knie links", cat="trauma",
         caus="unfallkausal")


def test_region_detection():
    assert region_of("Innenmeniskusriss") == "knie"
    assert region_of(None, "LWS-Syndrom") == "wirbelsäule"
    assert region_of("Prellung Oberarm") is None


def test_other_person_vs_typo(conn, case_id):
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    doc(conn, case_id, 3, name="Max Mustermann", dob="1963-03-12")   # typo-like
    doc(conn, case_id, 4, name="Anna Beispiel", dob="1975-07-04")    # someone else
    doc(conn, case_id, 5, name="Muster Max", dob="1961-03-12")       # same, reordered
    run_checks(conn, case_id)
    f = {r["document_id"]: r for r in findings(conn) if r["type"] == "identity_mismatch"}
    assert set(f) == {3, 4}
    assert f[3]["severity"] == "medium" and "Abweichende Personalien" in f[3]["claim"]
    assert f[4]["severity"] == "high" and "andere Person" in f[4]["claim"]


def test_case_dob_overrides_majority(conn, case_id):
    conn.execute("UPDATE cases SET patient_dob='1961-03-12'")
    doc(conn, case_id, 1, dob="1961-03-21")
    doc(conn, case_id, 2, dob="1961-03-21")
    run_checks(conn, case_id)
    assert {r["document_id"] for r in findings(conn)} == {1, 2}


def test_vorbefund_same_region_only(conn, case_id):
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    fact(conn, case_id, 2, "2021-03-14", "Gonarthrose links", caus="vorschaden")
    fact(conn, case_id, 2, "2021-06-22", "LWS-Beschwerden", side="na", region="LWS",
         cat="konservativ")
    run_checks(conn, case_id)
    f = findings(conn)
    assert [r["type"] for r in f] == ["predates_accident"]
    a, b = json.loads(f[0]["source_a"]), json.loads(f[0]["source_b"])
    assert a["global_seq"] == 2 and b["global_seq"] == 1  # Vorbefund vs. Unfall


def test_unfallkausal_before_accident_is_a_conflict(conn, case_id):
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    fact(conn, case_id, 2, "2023-09-01", "Meniskusriss links", caus="unfallkausal")
    run_checks(conn, case_id)
    f = findings(conn)
    assert len(f) == 1 and f[0]["type"] == "causality_conflict" and f[0]["severity"] == "high"


def test_laterality_conflict_after_accident(conn, case_id):
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    fact(conn, case_id, 2, "2024-07-02", "Schmerzen Knie rechts", side="rechts")
    fact(conn, case_id, 2, "2024-07-02", "Schulter rechts schmerzhaft", side="rechts",
         region="Schulter")  # other region: no conflict
    run_checks(conn, case_id)
    f = findings(conn)
    assert [r["type"] for r in f] == ["laterality_conflict"]
    assert f[0]["severity"] == "medium"


def test_same_operation_different_dates(conn, case_id):
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    doc(conn, case_id, 3)
    fact(conn, case_id, 2, "2023-11-14", "Arthroskopie Knie links, VKB-Plastik", cat="op")
    fact(conn, case_id, 3, "2023-11-15", "Arthroskopie Knie li., VKB-Plastik", cat="op")
    fact(conn, case_id, 3, "2024-09-01", "Arthroskopie Knie links, VKB-Plastik", cat="op")
    run_checks(conn, case_id)
    f = [r for r in findings(conn) if r["type"] == "date_contradiction"]
    assert len(f) == 1 and "2023-11-14" in f[0]["claim"] and "2023-11-15" in f[0]["claim"]


def test_implausible_dates(conn, case_id):
    conn.execute("UPDATE cases SET patient_dob='1961-03-12'")
    doc(conn, case_id, 1)
    fact(conn, case_id, 1, "1959-01-01", "Befund Knie", side="na")
    fact(conn, case_id, 1, "2099-01-01", "Kontrolle Knie", side="na")
    run_checks(conn, case_id)
    assert sorted(r["type"] for r in findings(conn)) == ["implausible_date"] * 2


def test_decisions_survive_rerun(conn, case_id):
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    fact(conn, case_id, 2, "2021-03-14", "Gonarthrose links")
    run_checks(conn, case_id)
    conn.execute("UPDATE findings SET status='rejected'")
    conn.commit()
    res = run_checks(conn, case_id)
    assert res["findings"] == 0 and res["kept_decisions"] == 1
    assert [r["status"] for r in findings(conn)] == ["rejected"]


def test_excluding_foreign_document_via_api(conn, case_id):
    from .test_api import client

    accident_docs(conn, case_id)
    doc(conn, case_id, 4, name="Anna Beispiel", dob="1975-07-04", title="Fremder Befund")
    fact(conn, case_id, 4, "2022-05-12", "Impingement Schulter rechts", side="rechts",
         region="Schulter")
    conn.commit()
    build_timeline(conn, case_id)
    run_checks(conn, case_id)
    assert any("Impingement" in r["title"] for r in
               conn.execute("SELECT title FROM timeline_entries"))
    r = client.patch(f"/api/cases/{case_id}/documents/4", json={"excluded": True})
    assert r.status_code == 200
    titles = [t["title"] for t in client.get(f"/api/cases/{case_id}/timeline").json()]
    assert not any("Impingement" in t for t in titles)
    open_f = [f for f in client.get(f"/api/cases/{case_id}/findings").json()
              if f["status"] == "open"]
    assert not any(f["document_id"] == 4 for f in open_f)
    fid = client.get(f"/api/cases/{case_id}/findings").json()
    assert client.post(f"/api/cases/{case_id}/findings/99999",
                       json={"status": "accepted"}).status_code == 404
    assert isinstance(fid, list)


def test_surname_only_is_same_person(conn, case_id):
    accident_docs(conn, case_id)
    doc(conn, case_id, 2, name="Widmer Daniel", dob="1981-08-30")
    doc(conn, case_id, 3, name="Widmer Daniel", dob="1981-08-30")
    doc(conn, case_id, 4, name="Widmer", dob=None)          # surname only
    doc(conn, case_id, 5, name="D. Widmer", dob="1981-08-30")  # initial
    conn.execute("UPDATE documents SET patient_name='Daniel Widmer', patient_dob='1981-08-30'"
                 " WHERE id=1")
    run_checks(conn, case_id)
    assert [r for r in findings(conn) if r["type"] == "identity_mismatch"] == []


def test_vorschaden_without_earlier_date_is_reported(conn, case_id):
    """'Schon vorher zwickte die Schulter' / 'seit 3-4 Jahren progredient': no earlier
    date, but labelled Vorschaden — must surface as a prior-condition note."""
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    fact(conn, case_id, 2, None, "Vorbestehende Kniebeschwerden", caus="vorschaden")
    fact(conn, case_id, 2, "2024-02-01", "Degenerative Meniskopathie seit Jahren",
         caus="vorschaden")
    fact(conn, case_id, 2, "2024-02-01", "LWS-Syndrom vorbestehend", caus="vorschaden",
         region="LWS", side="na")  # other region: not reported
    run_checks(conn, case_id)
    f = [r for r in findings(conn) if r["type"] == "predates_accident"]
    assert sorted(r["claim"] for r in f) == [
        "Vorzustand laut Akte: Degenerative Meniskopathie seit Jahren",
        "Vorzustand laut Akte: Vorbestehende Kniebeschwerden"]


def test_placeholder_names_are_ignored(conn, case_id):
    """'null'/'unbekannt' is the model saying 'no name found' — not another person."""
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    doc(conn, case_id, 3, name="null", dob=None)
    doc(conn, case_id, 4, name="unbekannt", dob=None)
    doc(conn, case_id, 5, name="Anna Beispiel", dob="1975-07-04")
    run_checks(conn, case_id)
    f = {r["document_id"]: r for r in findings(conn) if r["type"] == "identity_mismatch"}
    assert set(f) == {5}


def test_vorschaden_on_verdicts_is_not_a_prior_condition(conn, case_id):
    """Post-accident court/insurance determinations labelled 'vorschaden' must not
    each become a 'documented prior condition' finding."""
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    fact(conn, case_id, 2, "2024-01-01", "Einspracheentscheid: Abweisung",
         cat="korrespondenz", caus="vorschaden")
    fact(conn, case_id, 2, "2024-08-08", "Gerichtliche Feststellung: Vorschaden",
         cat="begutachtung", caus="vorschaden")
    fact(conn, case_id, 2, "2024-08-08", "Degenerative Meniskopathie seit Jahren",
         caus="vorschaden")  # clinical: still reported
    run_checks(conn, case_id)
    f = [r for r in findings(conn) if r["type"] == "predates_accident"]
    assert [r["claim"] for r in f] == [
        "Vorzustand laut Akte: Degenerative Meniskopathie seit Jahren"]


def test_merge_duplicate_facts(conn, case_id):
    """The same operation extracted several times under different titles: same
    doc + date + category + side merges into one; a different event on the same
    day does not."""
    from gutachten.analysis.extract import _merge_duplicate_facts
    accident_docs(conn, case_id)
    doc(conn, case_id, 2)
    fact(conn, case_id, 2, "2023-11-14", "Hernienreparation nach Lichtenstein links",
         cat="op")
    fact(conn, case_id, 2, "2023-11-14", "Operation Leistenhernie links", cat="op")
    fact(conn, case_id, 2, "2023-11-14", "Meniskusläsion rechts", cat="diagnostik",
         side="rechts")
    fact(conn, case_id, 2, "2023-11-15", "Physiotherapie", cat="konservativ")
    n = _merge_duplicate_facts(conn, case_id)
    assert n == 1
    rows = [dict(r) for r in conn.execute(
        "SELECT title FROM facts WHERE document_id=2 ORDER BY id")]
    assert [r["title"] for r in rows] == [
        "Hernienreparation nach Lichtenstein links", "Meniskusläsion rechts",
        "Physiotherapie"]
