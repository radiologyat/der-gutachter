# SPDX-License-Identifier: AGPL-3.0-or-later
"""One click: folder -> OCR -> Deckblatt -> verified details applied (marked, undoable)
-> Register, Aktenauszug, checks, draft. Fictitious data only."""
import time
from pathlib import Path

from gutachten.analysis import common
from gutachten.analysis.cover import list_suggestions, undo_suggestion
from gutachten.cases import get_case

from .test_analysis import ARZTBRIEF_1, ARZTBRIEF_2, AUFTRAG, MRI_1, OP, _pdf
from .test_api import client
from .test_drafting import DraftFake


def _wait(job_id, timeout=60):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_one_click_folder_to_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "get_llm", DraftFake)
    monkeypatch.setattr(common, "_extract_model_path", lambda: Path("model.gguf"))
    cid = client.post("/api/cases", json={"title": "Ordner-Test"}).json()["id"]
    files = [("files", (n, _pdf(tmp_path / n, pages).read_bytes(), "application/pdf"))
             for n, pages in (("01.pdf", [AUFTRAG]), ("02.pdf", [ARZTBRIEF_1, ARZTBRIEF_2]),
                              ("03.pdf", [MRI_1]), ("04.pdf", [OP]))]
    client.post(f"/api/cases/{cid}/files", files=files)
    job = _wait(client.post(f"/api/cases/{cid}/intake").json()["job_id"])
    assert job["status"] == "done", job
    r = job["result"]
    assert r["ocr"]["ok"] == 5 and r["auto_accepted"] >= 5
    assert r["index"]["documents"] == 4 and r["timeline"]["entries"] >= 3
    # client "Bezirksgericht …" -> assignment type Haftpflicht/Gericht, detected
    assert r["draft"]["template"] == "allgemein" and r["draft"]["failed"] == []

    case = get_case(cid)
    assert case["accident_date"] == "2023-10-09"  # from the Deckblatt, applied
    assert case["stage"] == "draft"
    sugg = list_suggestions(cid)
    auto = [s for s in sugg if s["auto"]]
    assert auto and all(s["status"] == "accepted" for s in auto)
    # the unverified (invented) Beweisfrage stays open for review
    assert any(s["status"] == "open" and "Arbeitsunfähigkeit" in s["payload"].get("text", "")
               for s in sugg)
    drafts = client.get(f"/api/cases/{cid}/drafts").json()
    assert [d["section_key"] for d in drafts][:3] == ["ausgangslage", "anamnese_aktenlage",
                                                      "befragung"]  # court template


def test_undo_restores_exactly(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "get_llm", DraftFake)
    monkeypatch.setattr(common, "_extract_model_path", lambda: Path("model.gguf"))
    cid = client.post("/api/cases", json={"title": "Undo", "auftraggeber": "Vorher AG"}
                      ).json()["id"]
    client.post(f"/api/cases/{cid}/files",
                files=[("files", ("a.pdf", _pdf(tmp_path / "a.pdf", [AUFTRAG]).read_bytes(),
                                  "application/pdf"))])
    _wait(client.post(f"/api/cases/{cid}/intake?full=false").json()["job_id"])
    client.post(f"/api/cases/{cid}/suggestions/accept-verified")
    assert get_case(cid)["auftraggeber"] == "Bezirksgericht Musterstadt"
    n_dates = len(client.get(f"/api/cases/{cid}/dates").json())
    n_q = len(client.get(f"/api/cases/{cid}/questions").json())
    for s in list_suggestions(cid):
        if s["status"] == "accepted":
            undo_suggestion(cid, s["id"])
    case = get_case(cid)
    assert case["auftraggeber"] == "Vorher AG" and case["accident_date"] is None
    assert len(client.get(f"/api/cases/{cid}/dates").json()) == n_dates - 1
    assert len(client.get(f"/api/cases/{cid}/questions").json()) == n_q - 2
    assert all(s["status"] == "open" for s in list_suggestions(cid))


def test_intake_without_model_stops_after_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "_extract_model_path", lambda: None)
    cid = client.post("/api/cases", json={"title": "Ohne Modell"}).json()["id"]
    client.post(f"/api/cases/{cid}/files",
                files=[("files", ("a.pdf", _pdf(tmp_path / "a.pdf", [AUFTRAG]).read_bytes(),
                                  "application/pdf"))])
    job = _wait(client.post(f"/api/cases/{cid}/intake").json()["job_id"])
    assert job["status"] == "done" and job["result"]["stopped"] == "kein Sprachmodell installiert"
    assert get_case(cid)["stage"] == "ocr"
