# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the full pipeline (import, OCR, cover, index, extract, timeline) on a
folder of PDFs/images with the configured local model, and print what came out.

    uv run python scripts/eval/run_folder.py samples/demo-akte [--out report.json]

Uses a throwaway GUTACHTEN_HOME (printed, so the case can be opened in the UI
with GUTACHTEN_HOME=<path>). No ground truth — for qualitative review.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOME = tempfile.mkdtemp(prefix="gutachten-run-")
os.environ["GUTACHTEN_HOME"] = HOME
sys.path.insert(0, str(ROOT / "src"))

from gutachten.analysis.cover import list_suggestions  # noqa: E402
from gutachten.analysis.runner import run_analysis  # noqa: E402
from gutachten.cases import SUPPORTED_SUFFIXES, connect_case, create_case  # noqa: E402
from gutachten.ingest.pipeline import import_file  # noqa: E402
from gutachten.llm.server import server  # noqa: E402
from gutachten.ocr.runner import ocr_pending_pages  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--accident-date")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    cid = create_case(args.folder.name, accident_date=args.accident_date)
    files = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)
    t0 = time.monotonic()
    imports = [{"file": f.name, **import_file(cid, f)} for f in files]
    ocr = ocr_pending_pages(cid)
    t_ocr = time.monotonic() - t0
    print(f"GUTACHTEN_HOME={HOME}\ncase={cid}\nOCR {ocr} in {t_ocr:.1f}s", flush=True)

    # cover first: its accepted accident date anchors causality in extraction
    t1 = time.monotonic()
    res = {"cover": run_analysis(cid, ["cover"])["cover"]}
    conn = connect_case(cid)
    for s in list_suggestions(cid):
        if s["kind"] == "case_field" and s["payload"]["field"] == "accident_date" \
                and s["verified"] and not args.accident_date:
            conn.execute("UPDATE cases SET accident_date=? WHERE id=?",
                         (s["payload"]["value"], cid))
            conn.commit()
    conn.close()
    res.update(run_analysis(cid, ["index", "extract", "timeline"],
                            progress=lambda s, d, t: print(f"\r  {s} {d}/{t}   ", end="",
                                                           flush=True)))
    t_an = time.monotonic() - t1
    print(f"\nanalysis {json.dumps(res)} in {t_an:.1f}s")

    conn = connect_case(cid)
    q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a)]  # noqa: E731
    report = {
        "home": HOME, "case": cid,
        "time_s": {"ocr": round(t_ocr, 1), "analysis": round(t_an, 1)},
        "imports": imports,
        "pages": q("""SELECT p.global_seq, s.orig_name, p.page_no, p.status,
                             p.has_embedded_text, p.image_coverage, p.phash,
                             (SELECT engine FROM ocr_runs r WHERE r.page_id=p.id
                              ORDER BY r.id DESC LIMIT 1) AS engine
                      FROM pages p JOIN sources s ON s.id=p.source_id ORDER BY p.global_seq"""),
        "case_row": dict(conn.execute("SELECT * FROM cases").fetchone()),
        "suggestions": [
            {"kind": s["kind"], "payload": s["payload"], "verified": s["verified"]}
            for s in list_suggestions(cid)
        ],
        "documents": q("""SELECT start_seq, end_seq, doc_type, doc_date, title,
                                 patient_name, patient_dob, boundary_reason, verify_note
                          FROM documents ORDER BY start_seq"""),
        "facts_unverified": q("""SELECT f.fact_date, f.title, f.verify_note, f.quote, p.global_seq
                                 FROM facts f JOIN pages p ON p.id=f.page_id
                                 WHERE verified=0"""),
        "timeline": q("""SELECT entry_date, date_end, category, causality, laterality,
                                title, json_array_length(citations) AS n_cit,
                                (SELECT group_concat(j.value ->> 'global_seq')
                                 FROM json_each(citations) j) AS bl
                         FROM timeline_entries ORDER BY entry_date, sort"""),
        "llm_calls": q("""SELECT stage, COUNT(*) n, ROUND(AVG(duration_ms)) avg_ms,
                                 SUM(status='error') errors FROM llm_calls GROUP BY stage"""),
    }
    conn.close()
    server.stop()
    print(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str),
                            encoding="utf-8")


if __name__ == "__main__":
    main()
