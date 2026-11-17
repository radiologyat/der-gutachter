# SPDX-License-Identifier: AGPL-3.0-or-later
import io
import time

from fastapi.testclient import TestClient

from gutachten.api.app import create_app

client = TestClient(create_app(), base_url="http://127.0.0.1:8077")


def _mk_pdf_bytes() -> bytes:
    import tempfile
    from pathlib import Path

    from .conftest import make_text_pdf

    with tempfile.TemporaryDirectory() as td:
        p = make_text_pdf(Path(td) / "a.pdf")
        return p.read_bytes()


def test_case_flow_via_api():
    r = client.post(
        "/api/cases",
        json={
            "title": "API Fall",
            "patient_ref": "XX",
            "jurisdiction": "CH",
            "case_type": "unfall",
            "accident_date": "2023-10-09",
            "auftraggeber": "FUV Fiktive Unfallversicherung",
        },
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    # upload
    r = client.post(
        f"/api/cases/{cid}/files",
        files=[("files", ("arztbrief.pdf", io.BytesIO(_mk_pdf_bytes()), "application/pdf"))],
    )
    assert r.status_code == 200
    assert r.json()["results"][0]["pages_added"] == 1

    # OCR (embedded text — no engine needed)
    r = client.post(f"/api/cases/{cid}/ocr", json={"engine": "tesseract"})
    job_id = r.json()["job_id"]
    for _ in range(60):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.5)
    assert job["status"] == "done"
    assert job["result"]["ok"] == 1

    # page list + detail
    pages = client.get(f"/api/cases/{cid}/pages").json()
    assert len(pages) == 1 and pages[0]["global_seq"] == 1
    page = client.get(f"/api/cases/{cid}/pages/1").json()
    assert "Max Muster" in page["text_md"]
    assert len(page["blocks"]) > 0

    # image served
    img = client.get(f"/api/cases/{cid}/pages/1/image")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"

    # manual correction
    r = client.put(
        f"/api/cases/{cid}/pages/1/text", json={"text": "Korrigierter Text."}
    )
    assert r.status_code == 200
    page = client.get(f"/api/cases/{cid}/pages/1").json()
    assert page["text_md"] == "Korrigierter Text."
    assert page["status"] == "manual"


def _new_case() -> str:
    return client.post("/api/cases", json={"title": "API Zusatz"}).json()["id"]


def test_foreign_host_header_rejected():
    """DNS-rebinding guard: a non-local Host must not reach patient data."""
    evil = TestClient(create_app(), base_url="http://evil.example")
    assert evil.get("/api/cases").status_code == 400


def test_unknown_case_is_404_everywhere():
    for path in ("/api/cases/nope", "/api/cases/nope/pages", "/api/cases/nope/dates",
                 "/api/cases/nope/questions", "/api/cases/nope/index"):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/cases/nope/ocr", json={}).status_code == 404
    r = client.post(
        "/api/cases/nope/files",
        files=[("files", ("a.pdf", io.BytesIO(_mk_pdf_bytes()), "application/pdf"))],
    )
    assert r.status_code == 404


def test_second_ocr_job_for_same_case_conflicts():
    import threading

    from gutachten.api import jobs as jobs_mod

    cid = _new_case()
    release = threading.Event()
    blocker = jobs_mod.jobs.start(cid, "ocr", lambda job: release.wait(5) and {})
    try:
        r = client.post(f"/api/cases/{cid}/ocr", json={"engine": "tesseract"})
        assert r.status_code == 409
        assert r.json()["detail"]["job_id"] == blocker.id
    finally:
        release.set()
    for _ in range(50):
        if blocker.status != "running":
            break
        time.sleep(0.05)
    r = client.post(f"/api/cases/{cid}/ocr", json={"engine": "tesseract"})
    assert r.status_code == 200  # free again once the first job finished


def test_page_blocks_come_from_latest_run_only():
    from gutachten.cases import connect_case
    from gutachten.ocr.runner import ocr_pending_pages

    cid = _new_case()
    client.post(
        f"/api/cases/{cid}/files",
        files=[("files", ("a.pdf", io.BytesIO(_mk_pdf_bytes()), "application/pdf"))],
    )
    ocr_pending_pages(cid)
    n_first = len(client.get(f"/api/cases/{cid}/pages/1").json()["blocks"])
    conn = connect_case(cid)  # force a re-run of the page
    conn.execute("UPDATE pages SET status='pending'")
    conn.commit()
    conn.close()
    ocr_pending_pages(cid)
    assert len(client.get(f"/api/cases/{cid}/pages/1").json()["blocks"]) == n_first


def test_upload_mixed_folder_reports_each_file():
    cid = _new_case()
    r = client.post(
        f"/api/cases/{cid}/files",
        files=[
            ("files", ("a.pdf", io.BytesIO(_mk_pdf_bytes()), "application/pdf")),
            ("files", (".DS_Store", io.BytesIO(b"junk"), "application/octet-stream")),
            ("files", ("kaputt.pdf", io.BytesIO(b"%PDF-1.4 garbage"), "application/pdf")),
        ],
    )
    assert r.status_code == 200
    statuses = [x["status"] for x in r.json()["results"]]
    assert statuses == ["ingested", "skipped", "error"]  # system file skipped
    assert len(client.get(f"/api/cases/{cid}/pages").json()) == 1


def test_upload_over_limit_rejected_per_file(monkeypatch):
    from gutachten import config

    cid = _new_case()
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 0)
    r = client.post(
        f"/api/cases/{cid}/files",
        files=[("files", ("a.pdf", io.BytesIO(_mk_pdf_bytes()), "application/pdf"))],
    )
    res = r.json()["results"][0]
    assert res["status"] == "error" and "zu gross" in res["reason"]
    assert client.get(f"/api/cases/{cid}/pages").json() == []


def test_user_actions_are_audited():
    from gutachten.cases import connect_case

    cid = _new_case()
    did = client.post(f"/api/cases/{cid}/dates",
                      json={"kind": "frist", "date": "2027-01-31", "label": "Abgabe"}).json()["id"]
    client.patch(f"/api/cases/{cid}/dates/{did}", json={"done": True})
    client.delete(f"/api/cases/{cid}/dates/{did}")
    client.post(f"/api/cases/{cid}/questions", json={"ord": 1, "text": "Unfallkausal?"})
    conn = connect_case(cid)
    actions = [r["action"] for r in conn.execute(
        "SELECT action FROM audit_log WHERE actor='user' ORDER BY id")]
    detail = conn.execute(
        "SELECT detail FROM audit_log WHERE action='date_deleted'").fetchone()["detail"]
    conn.close()
    assert actions == ["date_added", "date_done", "date_deleted", "question_added"]
    assert "2027-01-31" in detail


def test_analyze_endpoint_end_to_end(monkeypatch, tmp_path):
    from gutachten.analysis import common

    from .test_analysis import ARZTBRIEF_1, ARZTBRIEF_2, AUFTRAG, FakeLLM, _pdf

    cid = _new_case()
    # pending pages -> blocked
    pdf = _pdf(tmp_path / "a.pdf", [AUFTRAG])
    client.post(f"/api/cases/{cid}/files",
                files=[("files", ("a.pdf", pdf.read_bytes(), "application/pdf"))])
    assert client.post(f"/api/cases/{cid}/analyze", json={}).status_code == 400

    pdf2 = _pdf(tmp_path / "b.pdf", [ARZTBRIEF_1, ARZTBRIEF_2])
    client.post(f"/api/cases/{cid}/files",
                files=[("files", ("b.pdf", pdf2.read_bytes(), "application/pdf"))])
    client.post(f"/api/cases/{cid}/ocr", json={})
    for _ in range(60):
        if client.get(f"/api/cases/{cid}").json()["stats"]["pending"] == 0:
            break
        time.sleep(0.1)

    assert client.post(f"/api/cases/{cid}/analyze",
                       json={"steps": ["bogus"]}).status_code == 422
    monkeypatch.setattr(common, "get_llm", FakeLLM)
    job_id = client.post(
        f"/api/cases/{cid}/analyze",
        json={"steps": ["cover", "index", "extract", "timeline"]},
    ).json()["job_id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["result"]["index"]["documents"] == 2

    index = client.get(f"/api/cases/{cid}/index").json()
    assert [d["doc_type"] for d in index] == ["korrespondenz", "arztbrief"]
    tl = client.get(f"/api/cases/{cid}/timeline").json()
    assert tl[0]["citations"][0]["global_seq"] == 2  # parsed JSON, not a string
    unbelegt = client.get(f"/api/cases/{cid}/facts?verified=false").json()
    assert {f["title"] for f in unbelegt} == {"Kreuzbandplastik rechts", "Physiotherapie"}

    sugg = client.get(f"/api/cases/{cid}/suggestions").json()
    sid = next(s["id"] for s in sugg if s["kind"] == "date")
    assert client.post(f"/api/cases/{cid}/suggestions/{sid}",
                       json={"accept": True}).json() == {"status": "accepted"}
    assert client.post(f"/api/cases/{cid}/suggestions/99999",
                       json={"accept": True}).status_code == 404
    assert client.get(f"/api/cases/{cid}").json()["next_date"]["date"] == "2027-01-31"


def test_analyze_without_model_reports_error_in_job(monkeypatch):
    from gutachten import config

    monkeypatch.setattr(config, "EXTRACT_MODEL", None)
    monkeypatch.setattr(config, "EXTRACT_MODEL_DIR", config.ROOT / "nonexistent")
    cid = _new_case()
    client.post(f"/api/cases/{cid}/files",
                files=[("files", ("a.pdf", io.BytesIO(_mk_pdf_bytes()), "application/pdf"))])
    from gutachten.ocr.runner import ocr_pending_pages

    ocr_pending_pages(cid)
    job_id = client.post(f"/api/cases/{cid}/analyze", json={}).json()["job_id"]
    for _ in range(50):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "error" and "Sprachmodell Gemma 4 12B nicht gefunden" in job["error"]
    status = client.get("/api/llm/status").json()
    assert status["available"] is False and status["server_running"] is False


def test_disclaimer_acknowledgement_per_version(monkeypatch):
    import gutachten

    assert client.get("/api/system").json()["disclaimer_acknowledged"] is False
    ack = client.post("/api/disclaimer/acknowledge").json()
    assert ack["version"] == gutachten.DISCLAIMER_VERSION and ack["at"]
    assert client.get("/api/system").json()["disclaimer_acknowledged"] is True
    # a new disclaimer version must be acknowledged again
    monkeypatch.setattr(gutachten, "DISCLAIMER_VERSION", "2099-01-01")
    assert client.get("/api/system").json()["disclaimer_acknowledged"] is False


def test_running_job_lookup_is_read_only_and_bulk_accept():
    cid = _new_case()
    assert client.get(f"/api/cases/{cid}/jobs/running").json() == {"job_id": None}
    from gutachten.cases import connect_case

    assert connect_case(cid).execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE "
                                     "'timeline%'").fetchone()[0] == 0
    conn = connect_case(cid)
    conn.executemany(
        "INSERT INTO suggestions (case_id, kind, payload, verified) VALUES (?,?,?,?)",
        [(cid, "question", '{"text": "Frage A?"}', 1),
         (cid, "question", '{"text": "Frage B?"}', 0)])
    conn.commit()
    conn.close()
    assert client.post(f"/api/cases/{cid}/suggestions/accept-verified").json() == {"accepted": 1}
    open_ = [s for s in client.get(f"/api/cases/{cid}/suggestions").json()
             if s["status"] == "open"]
    assert len(open_) == 1 and open_[0]["verified"] == 0  # unverified stays for review
    assert [q["text"] for q in client.get(f"/api/cases/{cid}/questions").json()] == ["Frage A?"]
