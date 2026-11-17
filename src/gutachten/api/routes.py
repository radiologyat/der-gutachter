# SPDX-License-Identifier: AGPL-3.0-or-later
"""REST API for Der Gutachter."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import cases as cases_mod
from .. import config
from ..analysis import cover as cover_mod
from ..analysis import runner as analysis_runner
from ..cases import connect_case, create_case, get_case, list_cases
from ..db import database
from ..ingest.pipeline import import_file
from ..ocr import runner as ocr_runner
from .jobs import JobConflict, jobs
from .models import (
    AddDateRequest,
    AddQuestionRequest,
    AnalyzeRequest,
    CreateCaseRequest,
    DecideFindingRequest,
    DecideSuggestionRequest,
    DiagnosisRequest,
    ExpertProfile,
    RunOcrRequest,
    SetupImportRequest,
    SetupInstallRequest,
    UpdateCaseRequest,
    UpdateDateRequest,
    UpdateDocumentRequest,
    UpdatePageTextRequest,
    UpdateSectionRequest,
)

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"ok": True}


@router.get("/system")
def api_system() -> dict:
    """Where data lives and what is installed — shown on the landing page."""
    from .. import DISCLAIMER_VERSION, __version__
    from ..analysis.common import _extract_model_path

    model = _extract_model_path()
    ack = config.load_settings().get("disclaimer_ack") or {}
    return {
        "disclaimer_version": DISCLAIMER_VERSION,
        "disclaimer_acknowledged": ack.get("version") == DISCLAIMER_VERSION,
        "app": "Der Gutachter",
        "version": __version__,
        "data_home": str(config.DATA_HOME),
        "models_dir": str(config.MODELS_DIR),
        "extract_model": model.name if model else None,
        "tesseract": config.tesseract_cmd() is not None,
        "llama_server": config.llama_server_bin() is not None,
        "llm_backend": _llm_backend(),
    }


def _llm_backend() -> dict | None:
    from ..llm.server import server

    try:
        return server.backend_info()
    except Exception:  # noqa: BLE001 — informational only
        return None


@router.get("/setup/gpu-diagnostics")
def api_gpu_diagnostics() -> dict:
    """What the NVIDIA check saw (nvidia-smi path/output, Windows adapters)."""
    from .. import setup as setup_mod

    d = setup_mod.gpu_diagnostics()
    d["gpu"] = setup_mod.nvidia_gpu()
    d["llm_backend"] = _llm_backend()
    return d


@router.get("/disclaimer")
def api_disclaimer() -> dict:
    """Full disclaimer text (bundled with the app, readable offline)."""
    path = config.RESOURCE_DIR / "DISCLAIMER.md"
    return {"text": path.read_text(encoding="utf-8") if path.exists() else ""}


@router.post("/disclaimer/acknowledge")
def api_ack_disclaimer() -> dict:
    """Record that the user read and accepted the disclaimer (per user, per version)."""
    import datetime as dt

    from .. import DISCLAIMER_VERSION

    entry = {"version": DISCLAIMER_VERSION,
             "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
    config.save_settings({"disclaimer_ack": entry})
    return entry


# ---------------------------------------------------------------- cases

@router.post("/cases")
def api_create_case(req: CreateCaseRequest) -> dict:
    cid = create_case(**req.model_dump())
    return get_case(cid)


@router.get("/cases")
def api_list_cases() -> list[dict]:
    return [_with_pipeline_state(c) for c in list_cases()]


@router.get("/cases/{case_id}")
def api_get_case(case_id: str) -> dict:
    c = _with_pipeline_state(get_case(case_id))
    conn = connect_case(case_id)
    try:  # which pages the assignment was read from (shown in the overview)
        r = conn.execute("SELECT ref FROM llm_calls WHERE case_id=? AND stage='cover' "
                         "ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
    finally:
        conn.close()
    m = re.search(r"Bl\. (\d+)\D+(\d+)", r[0]) if r and r[0] else None
    c["cover_pages_read"] = [int(m.group(1)), int(m.group(2))] if m else None
    return c


@router.patch("/cases/{case_id}")
def api_update_case(case_id: str, req: UpdateCaseRequest) -> dict:
    get_case(case_id)
    data = req.model_dump(exclude_none=True)
    cases_mod.update_case(case_id, data)
    if "case_type" in data:  # the expert chose: no automatic change afterwards
        cases_mod.set_pipeline(case_id, case_type_by_user=True)
    return get_case(case_id)


# ---------------------------------------------------------------- report inputs (Phase 4b)

@router.get("/settings/expert")
def api_get_expert() -> dict:
    """The expert's own details (same for every report), kept in settings.json."""
    return ExpertProfile(**(config.load_settings().get("expert") or {})).model_dump()


@router.put("/settings/expert")
def api_put_expert(req: ExpertProfile) -> dict:
    config.save_settings({"expert": req.model_dump()})
    return req.model_dump()


def _json_field(case_id: str, column: str) -> dict:
    conn = connect_case(case_id)
    row = conn.execute(f"SELECT {column} FROM cases WHERE id=?", (case_id,)).fetchone()
    conn.close()
    return json.loads(row[0] or "{}")


def _save_json_field(case_id: str, column: str, data: dict, action: str) -> dict:
    conn = connect_case(case_id)
    conn.execute(f"UPDATE cases SET {column}=?, updated_at=datetime('now') WHERE id=?",
                 (json.dumps(data, ensure_ascii=False), case_id))
    database.audit(conn, case_id, action, "", actor="user")
    conn.commit()
    conn.close()
    return data


@router.get("/cases/{case_id}/exam")
def api_get_exam(case_id: str) -> dict:
    get_case(case_id)
    return _json_field(case_id, "exam_json")


@router.put("/cases/{case_id}/exam")
def api_put_exam(case_id: str, data: dict) -> dict:
    get_case(case_id)
    return _save_json_field(case_id, "exam_json", data, "exam_saved")


@router.get("/cases/{case_id}/answers")
def api_get_answers(case_id: str) -> dict:
    get_case(case_id)
    return _json_field(case_id, "answers_json")


@router.put("/cases/{case_id}/answers")
def api_put_answers(case_id: str, data: dict) -> dict:
    get_case(case_id)
    return _save_json_field(case_id, "answers_json", data, "answers_saved")


@router.get("/cases/{case_id}/interview")
def api_get_interview(case_id: str) -> dict:
    get_case(case_id)
    return _json_field(case_id, "interview_json")


@router.put("/cases/{case_id}/interview")
def api_put_interview(case_id: str, data: dict) -> dict:
    get_case(case_id)
    return _save_json_field(case_id, "interview_json", data, "interview_saved")


@router.get("/cases/{case_id}/interview/guide")
def api_interview_guide(case_id: str, model: bool = False) -> list[dict]:
    """Questions for the interview: standard topics, clarifications from the checks
    (each with reason and Bl.), Beweisfragen; with model=true also model-proposed
    clarifying questions per Beweisfrage (each citing its source entries)."""
    from ..analysis.common import LlmUnavailable, get_llm
    from ..analysis.interview import build_guide

    get_case(case_id)
    llm = None
    if model:
        try:
            llm = get_llm()
        except LlmUnavailable as e:
            raise HTTPException(400, str(e)) from None
    conn = connect_case(case_id)
    try:
        guide = build_guide(conn, case_id, llm)
        conn.commit()
        return guide
    finally:
        conn.close()


class _Text(BaseModel):
    text: str


@router.post("/cases/{case_id}/interview/indirect")
def api_indirect(case_id: str, req: _Text) -> dict:
    """Rewrite interview notes into indirect speech (a writing aid; the result is
    shown for review, with a warning if numbers, dates or sides changed)."""
    from ..analysis.common import LlmUnavailable, get_llm
    from ..analysis.interview import to_indirect

    get_case(case_id)
    try:
        llm = get_llm()
    except LlmUnavailable as e:
        raise HTTPException(400, str(e)) from None
    conn = connect_case(case_id)
    try:
        return to_indirect(conn, case_id, llm, req.text)
    finally:
        conn.close()


@router.get("/icd10")
def api_icd10(q: str = "") -> dict:
    from .. import icd10

    return {"results": icd10.search(q), "valid": icd10.valid_format(q),
            "normalized": icd10.normalize(q)}


@router.get("/setup/icd10")
def api_icd10_status() -> dict:
    from .. import icd10

    cat = icd10.catalog()
    return {"imported": cat is not None, "version": cat["version"] if cat else None,
            "codes": len(cat["codes"]) if cat else 0}


@router.post("/setup/icd10")
def api_icd10_import(file: UploadFile = File(...)) -> dict:  # noqa: B008
    """Import the ICD-10-GM ClaML/XML the user downloaded from bfarm.de."""
    from .. import icd10

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        path = Path(tmp.name)
    try:
        return icd10.import_claml(path)
    except Exception as e:  # any parse error is reported to the user
        raise HTTPException(400, f"Import fehlgeschlagen: {e}") from None
    finally:
        path.unlink(missing_ok=True)


@router.get("/cases/{case_id}/diagnoses")
def api_diagnoses(case_id: str) -> list[dict]:
    conn = connect_case(case_id)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM diagnoses WHERE case_id=? ORDER BY ord, id", (case_id,))]
    conn.close()
    return rows


def _diag_values(req: DiagnosisRequest) -> dict:
    from .. import icd10

    code = icd10.normalize(req.icd10)
    if code and not icd10.valid_format(code):
        raise HTTPException(422, f"Ungültiger ICD-10-Code: {req.icd10}")
    if code and icd10.exists(code) is False:
        raise HTTPException(422, f"Code nicht im ICD-10-GM-Katalog: {code}")
    return {**req.model_dump(exclude={"ord"}), "icd10": code}


@router.post("/cases/{case_id}/diagnoses")
def api_add_diagnosis(case_id: str, req: DiagnosisRequest) -> dict:
    v = _diag_values(req)
    conn = connect_case(case_id)
    n = conn.execute("SELECT COALESCE(MAX(ord),0)+1 FROM diagnoses WHERE case_id=?",
                     (case_id,)).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO diagnoses (case_id, ord, text, icd10, laterality, since, af_relevant,"
        " source, fact_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (case_id, req.ord or n, v["text"], v["icd10"], v["laterality"], v["since"],
         v["af_relevant"], v["source"], v["fact_id"]))
    database.audit(conn, case_id, "diagnosis_added", f"{v['icd10'] or '—'} {v['text']}",
                   actor="user")
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid}


@router.put("/cases/{case_id}/diagnoses/{did}")
def api_update_diagnosis(case_id: str, did: int, req: DiagnosisRequest) -> dict:
    v = _diag_values(req)
    conn = connect_case(case_id)
    cur = conn.execute(
        "UPDATE diagnoses SET text=?, icd10=?, laterality=?, since=?, af_relevant=?,"
        " ord=COALESCE(?, ord) WHERE id=? AND case_id=?",
        (v["text"], v["icd10"], v["laterality"], v["since"], v["af_relevant"], req.ord,
         did, case_id))
    conn.commit()
    conn.close()
    if not cur.rowcount:
        raise HTTPException(404, "diagnosis not found")
    return {"ok": True}


@router.delete("/cases/{case_id}/diagnoses/{did}")
def api_delete_diagnosis(case_id: str, did: int) -> dict:
    conn = connect_case(case_id)
    conn.execute("DELETE FROM diagnoses WHERE id=? AND case_id=?", (did, case_id))
    database.audit(conn, case_id, "diagnosis_deleted", str(did), actor="user")
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/cases/{case_id}/diagnoses/suggestions")
def api_diagnosis_suggestions(case_id: str) -> list[dict]:
    """Diagnoses named in the verified facts of the Akte, as suggestions with source."""
    from .. import icd10

    conn = connect_case(case_id)
    rows = [dict(r) for r in conn.execute(
        """SELECT f.id AS fact_id, f.title, f.icd10, f.laterality, f.fact_date, p.global_seq
           FROM facts f JOIN pages p ON p.id=f.page_id JOIN documents d ON d.id=f.document_id
           WHERE f.case_id=? AND f.verified=1 AND d.excluded=0
             AND (f.icd10 IS NOT NULL OR f.event_category IN ('diagnostik','vorbefund'))
           ORDER BY f.fact_date""", (case_id,))]
    taken = {(r[0] or "") for r in conn.execute(
        "SELECT icd10 FROM diagnoses WHERE case_id=?", (case_id,))}
    conn.close()
    # findings of the Akte that are clearly not diagnoses (referrals, follow-ups)
    not_diag = re.compile(r"^(u|ü)berweisung|kontrolle|konsultation|termin|verordnung|"
                          r"anmeldung|zuweisung", re.I)
    out, seen = [], set()
    for r in rows:
        if not r["icd10"] and not_diag.search(r["title"]):
            continue
        code = icd10.normalize(r["icd10"]) if icd10.valid_format(r["icd10"]) else None
        key = code or r["title"].lower()
        if key in seen or (code and code in taken):
            continue
        seen.add(key)
        out.append({**r, "icd10": code})
    return out


# ---------------------------------------------------------------- dates (Fristen/Termine)

@router.get("/cases/{case_id}/dates")
def api_dates(case_id: str) -> list[dict]:
    conn = connect_case(case_id)
    rows = cases_mod.list_dates(conn, case_id)
    conn.close()
    return rows


@router.post("/cases/{case_id}/dates")
def api_add_date(case_id: str, req: AddDateRequest) -> dict:
    return {"id": cases_mod.add_date(case_id, req.kind, req.date, req.label)}


@router.patch("/cases/{case_id}/dates/{date_id}")
def api_update_date(case_id: str, date_id: int, req: UpdateDateRequest) -> dict:
    cases_mod.update_date(case_id, date_id, req.done)
    return {"ok": True}


@router.delete("/cases/{case_id}/dates/{date_id}")
def api_delete_date(case_id: str, date_id: int) -> dict:
    cases_mod.delete_date(case_id, date_id)
    return {"ok": True}


# ---------------------------------------------------------------- files & ingest

# Plain `def`: FastAPI runs it in a worker thread. Rendering at 300 DPI is
# CPU-bound and would otherwise freeze the event loop (incl. job polling).
@router.post("/cases/{case_id}/files")
def api_upload(
    case_id: str, files: list[UploadFile] = File(...)  # noqa: B008 — FastAPI idiom
) -> dict:
    get_case(case_id)  # CaseNotFound -> 404
    results = []
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            shutil.copyfileobj(f.file, tmp)
            tmp_path = Path(tmp.name)
        size = tmp_path.stat().st_size
        if size > limit:
            tmp_path.unlink(missing_ok=True)
            results.append({
                "filename": f.filename, "status": "error", "pages_added": 0,
                "reason": f"Datei zu gross ({size // (1024 * 1024)} MB,"
                          f" Limit {config.MAX_UPLOAD_MB} MB)",
            })
            continue
        try:
            res = import_file(case_id, tmp_path, keep_name=False, orig_name=f.filename)
            res["filename"] = f.filename
            results.append(res)
        finally:
            tmp_path.unlink(missing_ok=True)
    return {"results": results}


# ---------------------------------------------------------------- OCR

@router.post("/cases/{case_id}/ocr")
def api_run_ocr(case_id: str, req: RunOcrRequest) -> dict:
    def _run(job):
        def progress(done, total, current):
            job.set_progress("Texterkennung", done, total)
            job.current = current

        return ocr_runner.ocr_pending_pages(
            case_id, preferred=req.engine, vlm_model=req.vlm_model,
            progress=progress,
        )

    get_case(case_id)
    if jobs.running(case_id, "analysis"):
        raise HTTPException(409, {"detail": "Auswertung läuft — OCR danach starten"})
    try:
        job = jobs.start(case_id, "ocr", _run)
    except JobConflict as e:
        raise HTTPException(
            409, {"detail": "OCR läuft bereits", "job_id": e.job.id}
        ) from None
    return {"job_id": job.id}


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def _with_pipeline_state(c: dict) -> dict:
    """A run marked "running" without a live job was interrupted (app closed,
    crash, PC switched off) — the UI offers to continue it."""
    p = c.get("pipeline") or {}
    if p.get("state") == "running" and not jobs.running(c["id"], "analysis"):
        p = {**p, "state": "interrupted"}
    job = jobs.running(c["id"], "analysis")
    c["pipeline"] = {**p, "job_status": job.status if job else None}
    return c


@router.get("/jobs-active")
def api_jobs_active() -> list[dict]:
    """Everything running right now, for the activity bar on every page."""
    out = []
    for j in jobs.active():
        d = j.to_dict()
        d.pop("result", None)
        if not j.case_id.startswith("_"):
            try:
                d["case_title"] = get_case(j.case_id)["title"]
            except Exception:  # noqa: BLE001
                d["case_title"] = j.case_id
        out.append(d)
    return out


@router.get("/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job.to_dict()


# ---------------------------------------------------------------- pages

def _page_by_seq(conn, case_id: str, seq: int):
    row = conn.execute(
        """SELECT p.*, s.filename, pt.text_md, pt.source AS text_source
           FROM pages p
           JOIN sources s ON s.id = p.source_id
           LEFT JOIN page_text pt ON pt.page_id = p.id
           WHERE p.case_id=? AND p.global_seq=?""",
        (case_id, seq),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"page Bl. {seq} not found")
    return dict(row)


@router.get("/cases/{case_id}/jobs/running")
def api_running_job(case_id: str) -> dict:
    """Read-only: the case's running background job (OCR or analysis), if any."""
    j = jobs.running(case_id, "analysis") or jobs.running(case_id, "ocr")
    return {"job_id": j.id if j else None}


@router.post("/jobs/{job_id}/cancel")
def api_cancel_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    job.cancel.set()
    return {"ok": True}


# ---------------------------------------------------------------- model setup

@router.get("/setup/status")
def api_setup_status() -> dict:
    from .. import setup as setup_mod

    st = setup_mod.status()
    running = jobs.running("_setup", "models")
    st["job_id"] = running.id if running else None
    return st


def _start_setup_job(fn) -> dict:
    try:
        job = jobs.start("_setup", "models", fn)
    except JobConflict as e:
        raise HTTPException(409, {"detail": "Einrichtung läuft bereits",
                                  "job_id": e.job.id}) from None
    return {"job_id": job.id}


@router.post("/setup/install")
def api_setup_install(req: SetupInstallRequest) -> dict:
    """Explicit user action: download the selected models (the app's only
    network access). Resumable; verified by SHA-256."""
    from .. import setup as setup_mod

    unknown = set(req.items) - set(setup_mod.BY_ID)
    if unknown or not req.items:
        raise HTTPException(422, f"unbekannte Komponenten: {sorted(unknown)}")
    return _start_setup_job(lambda job: setup_mod.install(req.items, job, job.cancel))


@router.post("/setup/import")
def api_setup_import(req: SetupImportRequest) -> dict:
    """Offline import from a folder (USB stick / share), verified by SHA-256."""
    from .. import setup as setup_mod

    folder = Path(req.folder).expanduser()
    if not folder.is_dir():
        raise HTTPException(400, f"Ordner nicht gefunden: {folder}")
    return _start_setup_job(
        lambda job: setup_mod.import_folder(folder, req.items, job, job.cancel))


@router.get("/cases/{case_id}/pages")
def api_pages(case_id: str, status: str | None = None) -> list[dict]:
    conn = connect_case(case_id)
    q = """SELECT p.id, p.global_seq, p.page_no, p.status, p.rotation,
                  p.has_embedded_text, p.width, p.height, s.filename,
                  substr(COALESCE(pt.text_md,''),1,200) AS snippet
           FROM pages p
           JOIN sources s ON s.id=p.source_id
           LEFT JOIN page_text pt ON pt.page_id=p.id
           WHERE p.case_id=?"""
    args: list = [case_id]
    if status:
        q += " AND p.status=?"
        args.append(status)
    q += " ORDER BY p.global_seq"
    rows = [dict(r) for r in conn.execute(q, args)]
    conn.close()
    return rows


@router.get("/cases/{case_id}/pages/{seq}")
def api_page(case_id: str, seq: int) -> dict:
    conn = connect_case(case_id)
    page = _page_by_seq(conn, case_id, seq)
    blocks = [
        dict(r)
        for r in conn.execute(
            # only the latest successful run — older runs stay for the audit trail
            """SELECT b.* FROM ocr_blocks b
               WHERE b.page_id=? AND b.run_id = (
                   SELECT MAX(r.id) FROM ocr_runs r
                   WHERE r.page_id=? AND r.status='ok')
               ORDER BY b.seq""",
            (page["id"], page["id"]),
        )
    ]
    conn.close()
    page["blocks"] = blocks
    return page


@router.get("/cases/{case_id}/pages/{seq}/image")
def api_page_image(case_id: str, seq: int) -> FileResponse:
    conn = connect_case(case_id)
    page = _page_by_seq(conn, case_id, seq)
    conn.close()
    path = config.case_dir(case_id) / page["image_path"]
    if not path.exists():
        raise HTTPException(404, "image missing")
    return FileResponse(path, media_type="image/png")


@router.put("/cases/{case_id}/pages/{seq}/text")
def api_update_text(case_id: str, seq: int, req: UpdatePageTextRequest) -> dict:
    conn = connect_case(case_id)
    page = _page_by_seq(conn, case_id, seq)
    conn.execute(
        """INSERT INTO page_text (page_id, text_md, source) VALUES (?,?, 'manual')
           ON CONFLICT(page_id) DO UPDATE SET text_md=excluded.text_md,
               source='manual', updated_at=datetime('now')""",
        (page["id"], req.text),
    )
    conn.execute("UPDATE pages SET status='manual' WHERE id=?", (page["id"],))
    database.audit(
        conn, case_id, "manual_text_edit", f"Bl. {seq} d.A.", actor="user"
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/cases/{case_id}/review")
def api_review_queue(case_id: str) -> list[dict]:
    return api_pages(case_id, status="review")


# ---------------------------------------------------------------- index / documents

@router.get("/cases/{case_id}/index")
def api_index(case_id: str) -> list[dict]:
    """Register of the Akte: segmented documents if present, otherwise a
    source-level grouping of pages (one row per imported file)."""
    conn = connect_case(case_id)
    docs = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM documents WHERE case_id=? ORDER BY start_seq", (case_id,)
        )
    ]
    if docs:
        conn.close()
        return docs
    rows = [
        dict(r)
        for r in conn.execute(
            """SELECT s.id, COALESCE(s.orig_name, s.filename) AS name,
                      MIN(p.global_seq) AS start_seq, MAX(p.global_seq) AS end_seq,
                      COUNT(*) AS pages, s.kind, s.imported_at
               FROM sources s JOIN pages p ON p.source_id = s.id
               WHERE s.case_id=? AND s.status='ingested'
               GROUP BY s.id ORDER BY MIN(p.global_seq)""",
            (case_id,),
        )
    ]
    conn.close()
    return rows


@router.get("/cases/{case_id}/timeline")
def api_timeline(case_id: str) -> list[dict]:
    conn = connect_case(case_id)
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM timeline_entries WHERE case_id=?"
            " ORDER BY entry_date, sort",
            (case_id,),
        )
    ]
    conn.close()
    for r in rows:
        r["citations"] = json.loads(r["citations"] or "[]")
    return rows


class TimelineEntryRequest(BaseModel):
    entry_date: str | None = None
    date_end: str | None = None
    category: str | None = None
    causality: str | None = None
    laterality: str | None = None
    body_region: str | None = None
    title: str | None = None
    summary: str | None = None
    seq: int | None = None      # page to cite (Bl.)
    quote: str | None = None


class FlagRequest(BaseModel):
    value: bool = True


def _iso(d: str | None) -> str | None:
    if not d:
        return d
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", d.strip())
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", d.strip()):
        return d.strip()
    raise HTTPException(422, f"Datum nicht lesbar: {d} (TT.MM.JJJJ)")


def _timeline_call(case_id: str, fn, *args):
    from ..analysis import timeline as tl

    get_case(case_id)
    conn = connect_case(case_id)
    try:
        out = getattr(tl, fn)(conn, case_id, *args)
    except KeyError:
        raise HTTPException(404, "Eintrag nicht gefunden") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    finally:
        conn.close()
    if isinstance(out, dict) and "citations" in out:
        out["citations"] = json.loads(out["citations"] or "[]")
    return out


@router.post("/cases/{case_id}/timeline")
def api_timeline_add(case_id: str, req: TimelineEntryRequest) -> dict:
    data = req.model_dump(exclude={"seq"})
    data["entry_date"], data["date_end"] = _iso(req.entry_date), _iso(req.date_end)
    if not data["entry_date"] or not (req.title or "").strip():
        raise HTTPException(422, "Datum und Titel sind erforderlich")
    return {"id": _timeline_call(case_id, "add_entry", data, req.seq)}


@router.patch("/cases/{case_id}/timeline/{eid}")
def api_timeline_update(case_id: str, eid: int, req: TimelineEntryRequest) -> dict:
    data = req.model_dump(exclude_unset=True, exclude={"seq", "quote"})
    for k in ("entry_date", "date_end"):
        if k in data:
            data[k] = _iso(data[k])
    return _timeline_call(case_id, "update_entry", eid, data)


@router.post("/cases/{case_id}/timeline/{eid}/restore")
def api_timeline_restore(case_id: str, eid: int) -> dict:
    return _timeline_call(case_id, "restore_entry", eid)


@router.post("/cases/{case_id}/timeline/{eid}/exclude")
def api_timeline_exclude(case_id: str, eid: int, req: FlagRequest) -> dict:
    return _timeline_call(case_id, "set_flag", eid, "excluded", req.value)


@router.post("/cases/{case_id}/timeline/{eid}/reviewed")
def api_timeline_reviewed(case_id: str, eid: int, req: FlagRequest) -> dict:
    return _timeline_call(case_id, "set_flag", eid, "reviewed", req.value)


@router.post("/cases/{case_id}/timeline-review-all")
def api_timeline_review_all(case_id: str) -> dict:
    return {"reviewed": _timeline_call(case_id, "review_all")}


@router.delete("/cases/{case_id}/timeline/{eid}")
def api_timeline_delete(case_id: str, eid: int) -> dict:
    _timeline_call(case_id, "delete_manual", eid)
    return {"ok": True}


@router.get("/cases/{case_id}/steps")
def api_steps(case_id: str) -> dict:
    from ..analysis.steps import overview

    get_case(case_id)
    conn = connect_case(case_id)
    try:
        return overview(conn, case_id)
    finally:
        conn.close()


AUDIT_LABEL = {"system": "Programm", "user": "Sachverständige/r"}


def _protocol(case_id: str) -> list[dict]:
    """Audit trail plus the model calls (which model, which prompt version)."""
    get_case(case_id)
    conn = connect_case(case_id)
    try:
        rows = [{"ts": r["ts"], "wer": AUDIT_LABEL.get(r["actor"], r["actor"]),
                 "aktion": r["action"], "detail": r["detail"] or ""}
                for r in conn.execute("SELECT * FROM audit_log WHERE case_id=? ORDER BY ts, id",
                                      (case_id,))]
        cols = {r[1] for r in conn.execute("PRAGMA table_info(llm_calls)")}
        if cols:
            ts = "created_at" if "created_at" in cols else "ts" if "ts" in cols else None
            for r in conn.execute(f"SELECT * FROM llm_calls WHERE case_id=? ORDER BY "
                                  f"{ts or 'id'}", (case_id,)):
                r = dict(r)
                rows.append({"ts": r.get(ts) if ts else "", "wer": "KI-Modell",
                             "aktion": f"ki_{r.get('stage')}",
                             "detail": " · ".join(str(x) for x in (
                                 r.get("ref"), r.get("model_id"), r.get("prompt_version"),
                                 r.get("status")) if x)})
    finally:
        conn.close()
    return sorted(rows, key=lambda r: r["ts"] or "")


@router.get("/cases/{case_id}/diagnostics")
def api_diagnostics(case_id: str) -> dict:
    from ..analysis.diagnostics import case_diagnostics

    get_case(case_id)
    conn = connect_case(case_id)
    try:
        d = case_diagnostics(conn, case_id)
    finally:
        conn.close()
    d["llm_backend"] = _llm_backend()
    return d


@router.get("/cases/{case_id}/protocol")
def api_protocol(case_id: str) -> list[dict]:
    return _protocol(case_id)


@router.get("/cases/{case_id}/protocol.csv")
def api_protocol_csv(case_id: str):
    import csv
    import io

    from fastapi.responses import Response

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Zeit (UTC)", "Wer", "Aktion", "Detail"])
    for r in _protocol(case_id):
        w.writerow([r["ts"], r["wer"], r["aktion"], r["detail"]])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="Protokoll-{case_id}.csv"'})


@router.get("/cases/{case_id}/facts")
def api_facts(case_id: str, verified: bool | None = None) -> list[dict]:
    conn = connect_case(case_id)
    q = """SELECT f.*, p.global_seq, d.title AS doc_title
           FROM facts f JOIN pages p ON p.id=f.page_id
           LEFT JOIN documents d ON d.id=f.document_id
           WHERE f.case_id=?"""
    args: list = [case_id]
    if verified is not None:
        q += " AND f.verified=?"
        args.append(int(verified))
    rows = [dict(r) for r in conn.execute(q + " ORDER BY f.fact_date, p.global_seq", args)]
    conn.close()
    for r in rows:
        r["block_ids"] = json.loads(r["block_ids"] or "[]")
        r["bbox"] = json.loads(r["bbox"]) if r["bbox"] else None
    return rows


# ---------------------------------------------------------------- analysis (Phase 2)

@router.post("/cases/{case_id}/analyze")
def api_analyze(case_id: str, req: AnalyzeRequest) -> dict:
    get_case(case_id)
    unknown = set(req.steps) - set(analysis_runner.STEPS)
    if unknown or not req.steps:
        raise HTTPException(422, f"unbekannte Schritte: {sorted(unknown)}")
    if jobs.running(case_id, "ocr"):
        raise HTTPException(409, {"detail": "OCR läuft noch"})
    try:
        analysis_runner.check_ready(case_id)
    except analysis_runner.AnalysisBlocked as e:
        raise HTTPException(400, str(e)) from None

    def _run(job):
        def progress(step, done, total):
            job.set_progress(step, done, total)

        return analysis_runner.run_analysis(case_id, req.steps, progress=progress,
                                            note=job.note)

    try:
        job = jobs.start(case_id, "analysis", _run)
    except JobConflict as e:
        raise HTTPException(
            409, {"detail": "Auswertung läuft bereits", "job_id": e.job.id}
        ) from None
    return {"job_id": job.id}


@router.get("/cases/{case_id}/findings")
def api_findings(case_id: str) -> list[dict]:
    conn = connect_case(case_id)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM findings WHERE case_id=?"
        " ORDER BY status='open' DESC, CASE severity WHEN 'high' THEN 0"
        " WHEN 'medium' THEN 1 ELSE 2 END, id", (case_id,))]
    conn.close()
    for r in rows:
        r["source_a"] = json.loads(r["source_a"]) if r["source_a"] else None
        r["source_b"] = json.loads(r["source_b"]) if r["source_b"] else None
    return rows


@router.post("/cases/{case_id}/findings/{fid}")
def api_decide_finding(case_id: str, fid: int, req: DecideFindingRequest) -> dict:
    conn = connect_case(case_id)
    row = conn.execute("SELECT type, claim FROM findings WHERE id=? AND case_id=?",
                       (fid, case_id)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "finding not found")
    conn.execute("UPDATE findings SET status=?, decided_at=datetime('now') WHERE id=?",
                 (req.status, fid))
    database.audit(conn, case_id, f"finding_{req.status}", f"{row['type']}: {row['claim']}",
                   actor="user")
    conn.commit()
    conn.close()
    return {"status": req.status}


@router.patch("/cases/{case_id}/documents/{doc_id}")
def api_update_document(case_id: str, doc_id: int, req: UpdateDocumentRequest) -> dict:
    """Exclude/include a document (e.g. misfiled foreign patient): its facts leave
    the Aktenauszug and the checks; rebuilt immediately."""
    from ..analysis.checks import run_checks
    from ..analysis.timeline import build_timeline

    conn = connect_case(case_id)
    row = conn.execute("SELECT title FROM documents WHERE id=? AND case_id=?",
                       (doc_id, case_id)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "document not found")
    conn.execute("UPDATE documents SET excluded=? WHERE id=?", (int(req.excluded), doc_id))
    database.audit(conn, case_id, "document_excluded" if req.excluded else "document_included",
                   row["title"], actor="user")
    conn.commit()
    timeline = build_timeline(conn, case_id)
    checks = run_checks(conn, case_id)
    conn.close()
    return {"excluded": req.excluded, "timeline": timeline, "checks": checks}


@router.get("/llm/status")
def api_llm_status() -> dict:
    from ..analysis.common import _extract_model_path
    from ..llm.client import LlamaClient

    client = LlamaClient()
    healthy = client.healthy()
    model = _extract_model_path()
    return {
        "server_running": healthy,
        "model_id": client.model_id if healthy else None,
        "model_file": model.name if model else None,
        "available": healthy or model is not None,
    }


@router.get("/cases/{case_id}/suggestions")
def api_suggestions(case_id: str) -> list[dict]:
    return cover_mod.list_suggestions(case_id)


@router.post("/cases/{case_id}/suggestions/accept-verified")
def api_accept_verified(case_id: str) -> dict:
    """Accept all suggestions whose quote was found in the Akte (one click);
    unverified ones stay open for individual review."""
    return {"accepted": cover_mod.accept_verified(case_id)}


@router.post("/cases/{case_id}/suggestions/{sid}/undo")
def api_undo_suggestion(case_id: str, sid: int) -> dict:
    try:
        return cover_mod.undo_suggestion(case_id, sid)
    except cases_mod.CaseNotFound:
        raise
    except KeyError:
        raise HTTPException(404, "suggestion not found") from None


@router.post("/cases/{case_id}/intake")
def api_intake(case_id: str, full: bool = True, vorentwurf: bool = False) -> dict:
    """One click after loading a folder: OCR, Deckblatt, verified details applied
    (marked "automatisch übernommen", undoable), then Register, Aktenauszug,
    checks and the draft. Without a language model it stops after OCR."""
    get_case(case_id)

    def _run(job):
        from ..analysis.common import _extract_model_path
        from ..analysis.cover import COVER_PAGES
        from ..llm.client import LlamaClient

        def oprogress(label):
            def progress(done, total, current):
                job.set_progress(label, done, total)
                job.current = current
            return progress

        def aprogress(step, done, total):
            job.set_progress(step, done, total)

        cases_mod.set_pipeline(case_id, state="running", vorentwurf=vorentwurf,
                               full=full, started=_now_iso(), error=None)
        try:
            out: dict = {}
            conn = connect_case(case_id)
            cover_done = conn.execute("SELECT 1 FROM step_marks WHERE case_id=? AND "
                                      "step='cover' AND ran_at IS NOT NULL",
                                      (case_id,)).fetchone()
            conn.close()
            have_model = bool(_extract_model_path() or LlamaClient().healthy())
            # 1. the assignment first: OCR of the first pages, then read the cover
            #    (client, accident date, deadlines, questions) — everything else
            #    builds on it
            out["ocr_deckblatt"] = ocr_runner.ocr_pending_pages(
                case_id, progress=oprogress("Texterkennung Auftrag"), max_seq=COVER_PAGES)
            if have_model and not cover_done and not _assignment_on_first_pages(case_id):
                # the assignment is not among the first pages: find it after the
                # recognition of all pages
                job.note("Auftrag nicht auf den ersten Seiten – wird nach der "
                         "Texterkennung gesucht")
                out["ocr_rest_first"] = ocr_runner.ocr_pending_pages(
                    case_id, progress=oprogress("Texterkennung"))
            if have_model and not cover_done:
                job.note("Gutachtenauftrag wird ausgelesen")
                out.update(analysis_runner.run_analysis(case_id, ["cover"],
                                                        progress=aprogress, note=job.note))
                if full:
                    out["auto_accepted"] = cover_mod.accept_verified(case_id, auto=True)
                    job.note(f"Auftrag: {out['auto_accepted']} belegte Angaben übernommen")
                    t = cover_mod.apply_case_type(case_id)
                    if t:
                        label = {"invaliditaet": "IV-Gutachten (KSVI)",
                                 "unfall": "Unfallversicherung (UVG)",
                                 "haftpflicht": "Haftpflicht / Gericht"}.get(t, t)
                        job.note(f"Auftragsart aus dem Auftraggeber erkannt: {label}")
            elif cover_done:
                job.note("Gutachtenauftrag bereits ausgelesen – übersprungen (Fortsetzen)")
            # 2. OCR of all other pages
            rest = ocr_runner.ocr_pending_pages(case_id, progress=oprogress("Texterkennung"))
            parts = [out.pop("ocr_deckblatt"), out.pop("ocr_rest_first", {}), rest]
            out["ocr"] = {k: sum(x.get(k, 0) for x in parts) for k in rest}
            o = out["ocr"]
            job.note("Texterkennung: alle Seiten bereits erkannt" if not o.get("total") else
                     f"Texterkennung fertig: {o.get('ok', 0)} von {o.get('total', 0)} Seiten"
                     + (f", {o['review']} zu prüfen" if o.get("review") else "")
                     + (f", {o['errors']} Fehler" if o.get("errors") else ""))
            if not have_model:
                out["stopped"] = "kein Sprachmodell installiert"
                cases_mod.set_pipeline(case_id, state="done", finished=_now_iso(),
                                       note=out["stopped"])
                return out
            if full:
                # 3. register, extraction, Aktenauszug, checks, draft (+ Vorentwurf).
                #    Model answers already given are reused: a resumed run continues
                #    where it stopped.
                steps = ["index", "extract", "timeline", "checks", "checks_ki", "draft"]
                if vorentwurf:
                    steps.append("vorentwurf")
                out.update(analysis_runner.run_analysis(case_id, steps, progress=aprogress,
                                                        note=job.note))
            cases_mod.set_pipeline(case_id, state="done", finished=_now_iso())
            return out
        except Exception as e:
            cases_mod.set_pipeline(case_id, state="error", error=str(e)[:300],
                                   finished=_now_iso())
            raise

    try:
        job = jobs.start(case_id, "analysis", _run)
    except JobConflict as e:
        raise HTTPException(409, {"detail": "läuft bereits", "job_id": e.job.id}) from None
    return {"job_id": job.id}


def _assignment_on_first_pages(case_id: str) -> bool:
    from ..analysis.common import page_texts
    from ..analysis.cover import COVER_PAGES, assignment_score

    conn = connect_case(case_id)
    try:
        if json.loads(conn.execute("SELECT pipeline_json FROM cases WHERE id=?",
                                   (case_id,)).fetchone()[0] or "{}").get("cover_pages"):
            return True
        pages = page_texts(conn, case_id)[:COVER_PAGES]
        return any(assignment_score(p["text"]) for p in pages)
    finally:
        conn.close()


class CoverPagesRequest(BaseModel):
    start: int
    end: int | None = None


@router.post("/cases/{case_id}/cover")
def api_cover_pages(case_id: str, req: CoverPagesRequest) -> dict:
    """The assignment is on Bl. start–end: read it from there (the automatic choice
    found the wrong pages). Verified details are applied and can be undone."""
    get_case(case_id)
    end = req.end or req.start
    if req.start < 1 or end < req.start or end - req.start > 9:
        raise HTTPException(422, "Bitte Blatt von–bis angeben (höchstens 10 Blätter)")
    cases_mod.set_pipeline(case_id, cover_pages=[req.start, end])

    def _run(job):
        def progress(done, total, current):
            job.set_progress("Texterkennung", done, total)

        out = {"ocr": ocr_runner.ocr_pending_pages(case_id, progress=progress, max_seq=end)}
        out.update(analysis_runner.run_analysis(
            case_id, ["cover"], progress=lambda s, d, t: job.set_progress(s, d, t),
            note=job.note))
        out["auto_accepted"] = cover_mod.accept_verified(case_id, auto=True)
        cover_mod.apply_case_type(case_id)
        return out

    try:
        job = jobs.start(case_id, "analysis", _run)
    except JobConflict as e:
        raise HTTPException(409, {"detail": "läuft bereits", "job_id": e.job.id}) from None
    return {"job_id": job.id}


@router.post("/cases/{case_id}/refresh")
def api_refresh(case_id: str, vorentwurf: bool | None = None) -> dict:
    """"Alles aktualisieren": text recognition of new pages, the cover if it was never
    read, then every analysis step that is missing or stale (and what follows it).
    Up-to-date steps are skipped; edited and approved sections are kept. Afterwards
    the step overview says what is still missing."""
    from ..analysis.steps import plan_refresh

    case = get_case(case_id)
    want_ki = bool((case.get("pipeline") or {}).get("vorentwurf")) if vorentwurf is None \
        else vorentwurf
    conn = connect_case(case_id)
    try:
        steps = plan_refresh(conn, case_id, want_ki)
        pending = conn.execute("SELECT COUNT(*) FROM pages WHERE case_id=? AND "
                               "status='pending'", (case_id,)).fetchone()[0]
        cover_done = conn.execute("SELECT 1 FROM step_marks WHERE case_id=? AND "
                                  "step='cover' AND ran_at IS NOT NULL",
                                  (case_id,)).fetchone()
    finally:
        conn.close()
    if not steps and not pending and cover_done:
        return {"up_to_date": True, "steps": []}

    def _run(job):
        from ..analysis.common import _extract_model_path
        from ..llm.client import LlamaClient

        def oprogress(done, total, current):
            job.set_progress("Texterkennung", done, total)
            job.current = current

        def aprogress(step, done, total):
            job.set_progress(step, done, total)

        cases_mod.set_pipeline(case_id, state="running", vorentwurf=want_ki,
                               started=_now_iso(), error=None)
        try:
            out: dict = {"planned": steps}
            if pending:
                out["ocr"] = ocr_runner.ocr_pending_pages(case_id, progress=oprogress)
                job.note(f"Texterkennung: {out['ocr'].get('ok', 0)} neue Seite(n)")
            if not (_extract_model_path() or LlamaClient().healthy()):
                out["stopped"] = "kein Sprachmodell installiert"
                cases_mod.set_pipeline(case_id, state="done", finished=_now_iso())
                return out
            if not cover_done:
                out.update(analysis_runner.run_analysis(case_id, ["cover"],
                                                        progress=aprogress, note=job.note))
                out["auto_accepted"] = cover_mod.accept_verified(case_id, auto=True)
                cover_mod.apply_case_type(case_id)
            todo = steps
            if pending or not cover_done:  # new pages or cover change everything after
                from ..analysis.steps import plan_refresh as _plan

                c2 = connect_case(case_id)
                try:
                    todo = _plan(c2, case_id, want_ki)
                finally:
                    c2.close()
            if todo:
                job.note("Wird aktualisiert: " + ", ".join(
                    analysis_runner.LABEL.get(s, s) for s in todo))
                out.update(analysis_runner.run_analysis(case_id, todo, progress=aprogress,
                                                        note=job.note))
            cases_mod.set_pipeline(case_id, state="done", finished=_now_iso())
            return out
        except Exception as e:
            cases_mod.set_pipeline(case_id, state="error", error=str(e)[:300],
                                   finished=_now_iso())
            raise

    try:
        job = jobs.start(case_id, "analysis", _run)
    except JobConflict as e:
        raise HTTPException(409, {"detail": "läuft bereits", "job_id": e.job.id}) from None
    return {"job_id": job.id, "steps": steps, "ocr_pages": pending}


@router.post("/cases/{case_id}/suggestions/{sid}")
def api_decide_suggestion(case_id: str, sid: int, req: DecideSuggestionRequest) -> dict:
    try:
        return cover_mod.decide_suggestion(case_id, sid, req.accept)
    except cases_mod.CaseNotFound:
        raise
    except KeyError:
        raise HTTPException(404, "suggestion not found") from None


@router.get("/cases/{case_id}/drafts")
def api_drafts(case_id: str) -> list[dict]:
    from ..analysis import report_sections as rs
    from ..analysis.drafting import approval_problems

    conn = connect_case(case_id)
    case = dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())
    keys = {k for k, _, _ in rs.TEMPLATES[rs.template_for(case)]}
    # sections of an earlier template stay stored but are not part of the report
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM draft_sections WHERE case_id=? ORDER BY ord", (case_id,)
        )
        if r["section_key"] in keys
    ]
    conn.close()
    from ..analysis.style_check import check_report

    style = check_report(rows)
    for r in rows:
        r["warnings"] = json.loads(r.get("warnings") or "[]")
        r["problems"] = approval_problems(r["content_md"])
        r["style"] = style.get(r["section_key"], [])
    return rows


@router.put("/cases/{case_id}/drafts/{key}")
def api_update_section(case_id: str, key: str, req: UpdateSectionRequest) -> dict:
    from ..analysis.drafting import ApprovalBlocked, update_section

    conn = connect_case(case_id)
    try:
        return update_section(conn, case_id, key, req.content_md, req.status)
    except KeyError:
        raise HTTPException(404, "section not found") from None
    except ApprovalBlocked as e:
        raise HTTPException(400, f"Freigabe nicht möglich: {e}") from None
    finally:
        conn.close()


@router.post("/cases/{case_id}/drafts/{key}/accept-proposals")
def api_accept_proposals(case_id: str, key: str) -> dict:
    from ..analysis.proposals import accept_proposals

    conn = connect_case(case_id)
    try:
        return {"accepted": accept_proposals(conn, case_id, key)}
    except KeyError:
        raise HTTPException(404, "section not found") from None
    finally:
        conn.close()


@router.get("/cases/{case_id}/export.docx")
def api_export_docx(case_id: str) -> FileResponse:
    """Word export. Marked ENTWURF on every page until all sections are approved."""
    from ..export import export_docx

    path, final = export_docx(case_id)
    return FileResponse(
        path, filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"X-Gutachten-Final": "1" if final else "0"},
    )


# ---------------------------------------------------------------- questions (Fragenkatalog)

@router.get("/cases/{case_id}/questions")
def api_questions(case_id: str) -> list[dict]:
    conn = connect_case(case_id)
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM questions WHERE case_id=? ORDER BY ord", (case_id,)
        )
    ]
    conn.close()
    return rows


@router.post("/cases/{case_id}/questions")
def api_add_question(case_id: str, req: AddQuestionRequest) -> dict:
    conn = connect_case(case_id)
    cur = conn.execute(
        "INSERT INTO questions (case_id, ord, text) VALUES (?,?,?)",
        (case_id, req.ord, req.text),
    )
    database.audit(conn, case_id, "question_added", f"{req.ord}. {req.text}", actor="user")
    conn.commit()
    conn.close()
    return {"id": cur.lastrowid}
