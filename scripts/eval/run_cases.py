# SPDX-License-Identifier: AGPL-3.0-or-later
"""Batch: full pipeline with the real local model over all cases in the
Arbeitsliste that are not analysed yet, then score against local
samples/<name>/expected.json where present. Contains no case data.

    uv run python scripts/eval/run_cases.py [--only NAME ...] [--out report.json]

Workflow per case (like a user would): OCR pending pages -> cover -> accept the
verified cover suggestions (sets accident date, questions) -> index -> extract ->
timeline -> checks -> draft.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from gutachten.analysis.cover import decide_suggestion, list_suggestions  # noqa: E402
from gutachten.analysis.runner import run_analysis  # noqa: E402
from gutachten.cases import connect_case, get_case, list_cases  # noqa: E402
from gutachten.llm.server import server  # noqa: E402
from gutachten.ocr.runner import ocr_pending_pages  # noqa: E402

PREFIX = "Testfall (fiktiv): "
# expected.json vocabulary -> our finding types
SYNONYM = {"vorbefund": "predates_accident", "symptom_vor_unfall": "predates_accident",
           "seitenkonflikt": "laterality_conflict", "fremde_person": "identity_mismatch"}
OURS = {"identity_mismatch", "predates_accident", "causality_conflict",
        "laterality_conflict", "date_contradiction", "implausible_date"}


def score(name: str, found: set[str]) -> dict | None:
    f = ROOT / "samples" / name / "expected.json"
    if not f.exists():
        return None
    exp = json.loads(f.read_text(encoding="utf-8"))
    want = {SYNONYM.get(x["type"], x["type"]) for x in exp.get("expect_findings", [])}
    forbid = {SYNONYM.get(t, t) for t in exp.get("no_findings_expected", [])}
    return {
        "expected_covered": sorted(want & OURS),
        "hit": sorted(want & OURS & found),
        "missed": sorted((want & OURS) - found),
        "not_covered_by_rules": sorted(want - OURS),
        "false_alarms": sorted(forbid & found),
    }


def run_case(c: dict) -> dict:
    cid, name = c["id"], c["title"].removeprefix(PREFIX)
    t0 = time.monotonic()
    rec: dict = {"case": name, "id": cid}
    try:
        if c["stats"]["pending"]:
            rec["ocr"] = ocr_pending_pages(cid)
        res = run_analysis(cid, ["cover"])
        for s in list_suggestions(cid):
            if s["status"] == "open":
                decide_suggestion(cid, s["id"], accept=bool(s["verified"]))
        case = get_case(cid)
        rec["accident_date"] = case["accident_date"]
        res.update(run_analysis(cid, ["index", "extract", "timeline", "checks", "draft"]))
        rec["result"] = res
        conn = connect_case(cid)
        rec["findings"] = [dict(r) for r in conn.execute(
            "SELECT type, severity, claim FROM findings WHERE status='open'")]
        rec["draft_warnings"] = sum(json.loads(r["warnings"] or "[]").__len__() for r in
                                    conn.execute("SELECT warnings FROM draft_sections"))
        rec["review_pages"] = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE status='review'").fetchone()[0]
        rec["llm_errors"] = conn.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE status='error'").fetchone()[0]
        conn.close()
        rec["score"] = score(name, {f["type"] for f in rec["findings"]})
    except Exception as e:  # one bad case must not stop the batch
        rec["error"] = repr(e)
    rec["seconds"] = round(time.monotonic() - t0)
    rec["pages"] = c["stats"]["pages"]
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    todo = [c for c in list_cases()
            if c["stage"] in ("intake", "ocr")
            and (not args.only or c["title"].removeprefix(PREFIX) in args.only)]
    print(f"{len(todo)} cases to analyse", flush=True)
    report = []
    for i, c in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {c['title']} ({c['stats']['pages']} Bl.) ...", flush=True)
        rec = run_case(c)
        report.append(rec)
        if args.out:
            args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str),
                                encoding="utf-8")
        s = rec.get("score") or {}
        print(f"    {rec['seconds']} s | findings {[f['type'] for f in rec.get('findings', [])]}"
              f" | hit {s.get('hit')} missed {s.get('missed')} false {s.get('false_alarms')}"
              f"{' | ERROR ' + rec['error'] if 'error' in rec else ''}", flush=True)
    server.stop()


if __name__ == "__main__":
    main()
