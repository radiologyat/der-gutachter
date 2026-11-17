# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run OCR over a case's pages and persist results with full provenance.

Engine selection per page:
  - embedded text layer present      -> pdf_text (free, 100% confidence)
  - otherwise                        -> configured engine ('tesseract' default,
                                       'vlm' when a vision model is installed)
Low-confidence pages are flagged status='review' for the manual review queue.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .. import config
from ..cases import connect_case
from ..db import database
from .pdf_text import PdfTextEngine
from .tesseract_engine import TesseractEngine
from .vlm import VlmEngine

ProgressFn = Callable[[int, int, int], None]  # done, total, current_seq


def _engine_for(page: dict, preferred: str, vlm_model: str | None):
    if page["has_embedded_text"]:
        return PdfTextEngine()
    if preferred == "vlm" and vlm_model:
        return VlmEngine(vlm_model)
    return TesseractEngine()


def ocr_pending_pages(
    case_id: str,
    preferred: str = "tesseract",
    vlm_model: str | None = None,
    progress: ProgressFn | None = None,
    max_seq: int | None = None,
) -> dict:
    """OCR all pending pages (or only those up to Bl. max_seq — the cover first)."""
    cdir = config.case_dir(case_id)
    conn = connect_case(case_id)
    try:
        rows = conn.execute(
            """SELECT p.*, s.filename FROM pages p
               JOIN sources s ON s.id = p.source_id
               WHERE p.case_id=? AND p.status IN ('pending')
                 AND p.global_seq <= ?
               ORDER BY p.global_seq""",
            (case_id, max_seq if max_seq is not None else 10**9),
        ).fetchall()
        total = len(rows)
        done = ok = flagged = errors = 0
        for row in rows:
            page = dict(row)
            done += 1
            if progress:
                progress(done, total, page["global_seq"])
            engine = _engine_for(page, preferred, vlm_model)
            run_id = _start_run(conn, page["id"], engine)
            try:
                result = engine.ocr_page(page, cdir)
            except Exception as e:  # keep going — one bad page must not kill the batch
                _finish_run(conn, run_id, "error", str(e))
                conn.execute("UPDATE pages SET status='review' WHERE id=?", (page["id"],))
                conn.commit()
                errors += 1
                continue

            # orientation correction: re-OCR once if clearly rotated
            if isinstance(engine, TesseractEngine) and result.confidence < 0.4:
                rot = engine.detect_rotation(cdir / page["image_path"])
                if rot:
                    w, h = _rotate_image(cdir / page["image_path"], rot)
                    conn.execute(
                        "UPDATE pages SET rotation=?, width=?, height=? WHERE id=?",
                        (rot, w, h, page["id"]),
                    )
                    result = engine.ocr_page(page, cdir)

            _persist_result(conn, page, run_id, result)
            ok += 1
            flagged += result.confidence < config.OCR_REVIEW_THRESHOLD
            conn.commit()
        database.audit(
            conn, case_id, "ocr_batch",
            f"{ok}/{total} pages ok, {flagged} flagged for review, {errors} errors",
        )
        if total:
            from ..analysis.steps import mark_run

            mark_run(conn, case_id, "ocr")
        conn.commit()
        return {"total": total, "ok": ok, "review": flagged, "errors": errors}
    finally:
        conn.close()


def _engine_version(engine) -> str:
    # A missing binary (e.g. Tesseract not installed) must fail the page, not the batch.
    try:
        return engine.version()
    except Exception as e:
        return f"unavailable: {type(e).__name__}"


def _start_run(conn, page_id: int, engine) -> int:
    cur = conn.execute(
        """INSERT INTO ocr_runs (page_id, engine, engine_version, model_id, prompt_version)
           VALUES (?,?,?,?,?)""",
        (page_id, engine.name, _engine_version(engine), getattr(engine, "model_id", None),
         getattr(engine, "prompt_version", None)),
    )
    return cur.lastrowid


def _finish_run(conn, run_id: int, status: str, error: str | None = None):
    conn.execute(
        "UPDATE ocr_runs SET status=?, error=?, finished_at=datetime('now') WHERE id=?",
        (status, error, run_id),
    )


def _persist_result(conn, page: dict, run_id: int, result) -> None:
    for i, b in enumerate(result.blocks):
        conn.execute(
            """INSERT INTO ocr_blocks
               (page_id, run_id, seq, text, x0, y0, x1, y1, confidence, block_type)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (page["id"], run_id, i, b.text, b.x0, b.y0, b.x1, b.y1,
             b.confidence, b.block_type),
        )
    status = "review" if result.confidence < config.OCR_REVIEW_THRESHOLD else "ocr_done"
    source = "embedded" if result.engine == "pdf_text" else "ocr"
    conn.execute(
        """INSERT INTO page_text (page_id, text_md, source)
           VALUES (?,?,?)
           ON CONFLICT(page_id) DO UPDATE SET text_md=excluded.text_md,
               source=excluded.source, updated_at=datetime('now')""",
        (page["id"], result.text, source),
    )
    conn.execute("UPDATE pages SET status=? WHERE id=?", (status, page["id"]))
    _finish_run(conn, run_id, "ok")


def _rotate_image(path: Path, degrees: int) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as img:
        rotated = img.rotate(-degrees, expand=True)
    rotated.save(path)
    return rotated.width, rotated.height
