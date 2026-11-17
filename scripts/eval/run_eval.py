# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase-2 evaluation against a real local LLM on the synthetic Akte.

    uv run python scripts/eval/run_eval.py [--out report.json] [--keep]

Case material is local-only (samples/eval/, gitignored).
Builds the Akte (one file image-only -> Tesseract), runs OCR + cover + index +
extract + timeline with the configured model, and scores against ground truth:
segmentation P/R, doc-type/date accuracy, verified-fact share, key-event recall,
cover fields. Uses a throwaway GUTACHTEN_HOME unless --keep.
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
if "--keep" not in sys.argv:
    os.environ["GUTACHTEN_HOME"] = tempfile.mkdtemp(prefix="gutachten-eval-")
sys.path.insert(0, str(ROOT / "src"))
# Case definitions (synthetic Akten + ground truth) are local-only test material,
# never in git: samples/eval/akte_knie.py
CASES = ROOT / "samples" / "eval"
if not (CASES / "akte_knie.py").exists():
    raise SystemExit(f"Evaluation case not found: {CASES / 'akte_knie.py'}"
                     " (local-only, not in git)")
sys.path.insert(0, str(CASES))

import pymupdf as fitz  # noqa: E402
from akte_knie import (  # noqa: E402
    COVER_TRUTH,
    DOCS,
    FILES,
    KEY_EVENTS,
    TRUTH,
    TYPE_ALTERNATIVES,
)

from gutachten.analysis.cover import list_suggestions  # noqa: E402
from gutachten.analysis.runner import run_analysis  # noqa: E402
from gutachten.cases import connect_case, create_case  # noqa: E402
from gutachten.ingest.pipeline import import_file  # noqa: E402
from gutachten.llm.server import server  # noqa: E402
from gutachten.ocr.runner import ocr_pending_pages  # noqa: E402


def make_pdf(path: Path, pages: list[str], scan: bool) -> None:
    doc = fitz.open()
    for text in pages:
        p = doc.new_page(width=595, height=842)
        p.insert_textbox(fitz.Rect(60, 60, 540, 790), text, fontsize=10.5, fontname="helv")
    if scan:  # image-only, like a real scan
        out = fitz.open()
        for p in doc:
            png = p.get_pixmap(dpi=200).tobytes("png")
            np_ = out.new_page(width=595, height=842)
            np_.insert_image(np_.rect, stream=png)
        doc.close()
        doc = out
    doc.save(path)
    doc.close()


def truth_layout() -> list[tuple[str, int, int]]:
    out, seq = [], 0
    for _f, keys, _scan in FILES:
        for k in keys:
            n = len(DOCS[k])
            out.append((k, seq + 1, seq + n))
            seq += n
    return out


def rows(conn, sql, *a):
    return [dict(r) for r in conn.execute(sql, a)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="akte-"))
    cid = create_case("Eval Knie", jurisdiction="CH", accident_date="2023-10-09")
    t0 = time.monotonic()
    for fname, keys, scan in FILES:
        pages = [p for k in keys for p in DOCS[k]]
        make_pdf(work / fname, pages, scan)
        import_file(cid, work / fname)
    ocr = ocr_pending_pages(cid)
    t_ocr = time.monotonic() - t0
    print(f"OCR: {ocr} in {t_ocr:.1f}s")

    t1 = time.monotonic()
    res = run_analysis(cid, ["cover", "index", "extract", "timeline"],
                       progress=lambda s, d, t: print(f"\r  {s} {d}/{t}   ", end="", flush=True))
    t_an = time.monotonic() - t1
    print(f"\nAnalysis: {json.dumps(res)} in {t_an:.1f}s")

    conn = connect_case(cid)
    layout = truth_layout()
    docs = rows(conn, "SELECT * FROM documents ORDER BY start_seq")
    true_starts = {s for _, s, _ in layout}
    pred_starts = {d["start_seq"] for d in docs}
    tp = len(true_starts & pred_starts)
    seg_p, seg_r = tp / len(pred_starts), tp / len(true_starts)

    type_ok = date_ok = matched = 0
    doc_detail = []
    for key, s, e in layout:
        d = next((x for x in docs if x["start_seq"] == s and x["end_seq"] == e), None)
        t = TRUTH[key]
        if d:
            matched += 1
            ok_t = d["doc_type"] in TYPE_ALTERNATIVES.get(key, {t["type"]})
            allowed = t["date"] if isinstance(t["date"], list) else [t["date"]]
            ok_d = d["doc_date"] in allowed
            type_ok += ok_t
            date_ok += ok_d
        doc_detail.append({
            "doc": key, "truth": [s, e, t["type"], t["date"]],
            "pred": [d["start_seq"], d["end_seq"], d["doc_type"], d["doc_date"], d["title"]]
            if d else None,
        })

    facts = rows(conn, "SELECT verified, verify_note, title, fact_date FROM facts")
    n_ver = sum(f["verified"] for f in facts)
    timeline = rows(conn, "SELECT entry_date, title, summary FROM timeline_entries")
    ev_hits = []
    for prefix, kws in KEY_EVENTS:
        hit = any(
            e["entry_date"].startswith(prefix)
            and any(k in f"{e['title']} {e['summary']}".casefold() for k in kws)
            for e in timeline
        )
        ev_hits.append((prefix, hit))

    sugg = list_suggestions(cid)
    vals = {s["payload"].get("field"): s for s in sugg if s["kind"] == "case_field"}
    cover = {
        f: bool(vals.get(f)) and vals[f]["payload"]["value"] == v and vals[f]["verified"] == 1
        for f, v in COVER_TRUTH.items() if f not in ("deadline", "questions")
    }
    cover["deadline"] = any(s["kind"] == "date" and s["payload"]["date"] == COVER_TRUTH["deadline"]
                            and s["verified"] for s in sugg)
    nq = sum(1 for s in sugg if s["kind"] == "question" and s["verified"])
    cover["questions"] = f"{nq}/{COVER_TRUTH['questions']}"

    calls = rows(conn, "SELECT stage, COUNT(*) n, AVG(duration_ms) avg_ms,"
                       " SUM(status='error') errors FROM llm_calls GROUP BY stage")
    conn.close()

    report = {
        "model": calls and server.loaded_model and server.loaded_model.name,
        "pages": layout[-1][2],
        "time_s": {"ocr": round(t_ocr, 1), "analysis": round(t_an, 1)},
        "segmentation": {"precision": round(seg_p, 3), "recall": round(seg_r, 3),
                         "exact_docs": f"{matched}/{len(layout)}"},
        "doc_type_acc": f"{type_ok}/{matched}",
        "doc_date_acc": f"{date_ok}/{matched}",
        "facts": {"total": len(facts), "verified": n_ver,
                  "verified_share": round(n_ver / max(len(facts), 1), 3)},
        "unverified_reasons": sorted({(f["verify_note"] or "")[:60] for f in facts
                                      if not f["verified"]}),
        "key_events": {p: h for p, h in ev_hits},
        "key_event_recall": f"{sum(h for _, h in ev_hits)}/{len(ev_hits)}",
        "timeline_entries": len(timeline),
        "cover": cover,
        "llm_calls": calls,
        "documents": doc_detail,
        "timeline": sorted(f"{e['entry_date']}  {e['title']}" for e in timeline),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    server.stop()


if __name__ == "__main__":
    main()
