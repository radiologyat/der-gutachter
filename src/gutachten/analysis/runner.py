# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run analysis steps in order: cover -> index -> extract -> timeline."""
from __future__ import annotations

from collections.abc import Callable

from ..cases import connect_case
from ..llm.client import JsonLLM
from . import common
from .checks import run_checks
from .common import Progress
from .cover import run_cover
from .drafting import generate_draft
from .extract import run_extract
from .segment import run_index
from .steps import mark_run
from .timeline import build_timeline

STEPS = ("cover", "index", "extract", "timeline", "checks", "checks_ki", "draft", "vorentwurf")
NEEDS_LLM = {"cover", "index", "extract", "checks_ki", "draft", "vorentwurf"}


LABEL = {"cover": "Gutachtenauftrag", "index": "Registrierung", "extract": "Extraktion",
         "timeline": "Aktenauszug", "checks": "Prüfung", "checks_ki": "KI-Prüfung",
         "draft": "Entwurf", "vorentwurf": "KI-Vorentwurf"}


def summarize(step: str, r: dict) -> str:
    """One line per finished step for the activity log and protocol."""
    f = {
        "cover": lambda: f"{r.get('suggestions', 0)} Angaben erkannt, "
                         f"{r.get('verified', 0)} belegt"
                         + (f" (Bl. {r['pages'][0]}–{r['pages'][1]})" if r.get("pages")
                            else ""),
        "index": lambda: f"{r.get('documents', 0)} Dokumente aus {r.get('pages', 0)} Seiten"
                         + (f", {r['llm_failures']} Modellfehler" if r.get("llm_failures")
                            else ""),
        "extract": lambda: f"{r.get('facts', 0)} Angaben, {r.get('verified', 0)} belegt"
                           + (f", {r['llm_failures']} Modellfehler" if r.get("llm_failures")
                              else ""),
        "timeline": lambda: f"{r.get('entries', 0)} Einträge",
        "checks": lambda: f"{r.get('findings', 0)} Hinweise",
        "checks_ki": lambda: f"{r.get('findings', 0)} KI-Hinweise"
                             + (f", {r['dropped']} verworfen" if r.get("dropped") else ""),
        "draft": lambda: f"Vorlage {r.get('template')}, {len(r.get('generated', []))} "
                         "Abschnitte",
        "vorentwurf": lambda: f"{r.get('proposals', 0)} KI-Vorschläge",
    }.get(step, lambda: "")
    return f"{LABEL.get(step, step)} fertig: {f()}"


class AnalysisBlocked(RuntimeError):
    pass


def check_ready(case_id: str) -> None:
    conn = connect_case(case_id)
    try:
        r = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(status='pending'),0) p FROM pages WHERE case_id=?",
            (case_id,),
        ).fetchone()
    finally:
        conn.close()
    if r["c"] == 0:
        raise AnalysisBlocked("Keine Seiten in der Akte.")
    if r["p"]:
        raise AnalysisBlocked(f"{r['p']} Seite(n) ohne Texterkennung — erst OCR ausführen.")


def run_analysis(
    case_id: str,
    steps: list[str],
    progress: Progress | None = None,
    llm_factory: Callable[[], JsonLLM] | None = None,
    note: Callable[[str], None] | None = None,
) -> dict:
    steps = [s for s in STEPS if s in steps]  # canonical order
    factory = llm_factory or common.get_llm  # looked up late: tests patch it
    llm = factory() if NEEDS_LLM & set(steps) else None
    results: dict = {}
    conn = connect_case(case_id)
    try:
        for step in steps:
            if progress:
                progress(LABEL.get(step, step), 0, 0)
            if step == "cover":
                results["cover"] = run_cover(conn, case_id, llm)
            elif step == "index":
                results["index"] = run_index(conn, case_id, llm, progress)
            elif step == "extract":
                results["extract"] = run_extract(conn, case_id, llm, progress)
            elif step == "timeline":
                results["timeline"] = build_timeline(conn, case_id)
            elif step == "checks":
                results["checks"] = run_checks(conn, case_id)
            elif step == "checks_ki":
                from .llm_checks import run_llm_checks

                results["checks_ki"] = run_llm_checks(conn, case_id, llm)
            elif step == "draft":
                results["draft"] = generate_draft(conn, case_id, llm, progress=progress)
            elif step == "vorentwurf":
                from .proposals import run_proposals

                results["vorentwurf"] = run_proposals(conn, case_id, llm, progress=progress)
            mark_run(conn, case_id, step)
            conn.commit()
            if note:
                note(summarize(step, results.get(step) or {}))
    finally:
        conn.close()
    return results
