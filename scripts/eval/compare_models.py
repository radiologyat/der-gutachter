# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compare language models on local cases (samples/<name>/, never in git).

    GUTACHTEN_EXTRACT_MODEL=<gguf> uv run python scripts/eval/compare_models.py \
        <label> <out_dir> CASE [CASE ...]

Full pipeline incl. KI-Prüfung and KI-Vorentwurf per case. Writes report.json (counts,
findings, scores against expected.json, model call times) and one Markdown file per
case with the Vorentwurf and the Aktenauszug, for reading side by side. A throwaway
GUTACHTEN_HOME and its own llama port (8079) ensure that a running app's model server
is never used by accident.
Contains no case data.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["GUTACHTEN_HOME"] = tempfile.mkdtemp(prefix="gutachten-cmp-")
os.environ.setdefault("GUTACHTEN_LLAMA_PORT", "8079")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_cases import score  # noqa: E402

from gutachten.analysis import cover as cover_mod  # noqa: E402
from gutachten.analysis.runner import run_analysis  # noqa: E402
from gutachten.cases import SUPPORTED_SUFFIXES, connect_case, create_case  # noqa: E402
from gutachten.ingest.pipeline import import_file  # noqa: E402
from gutachten.llm.server import server  # noqa: E402
from gutachten.ocr.runner import ocr_pending_pages  # noqa: E402

label, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
report = []
for name in sys.argv[3:]:
    folder = ROOT / "samples" / name
    rec: dict = {"case": name, "model": label}
    t0 = time.monotonic()
    cid = create_case(f"Testfall (fiktiv): {name}")
    try:
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in SUPPORTED_SUFFIXES:
                import_file(cid, f)
        ocr_pending_pages(cid)
        times = {}
        t = time.monotonic()
        run_analysis(cid, ["cover"])
        cover_mod.accept_verified(cid, auto=True)
        cover_mod.apply_case_type(cid)
        times["cover"] = round(time.monotonic() - t)
        for step in ("index", "extract", "timeline", "checks", "checks_ki", "draft",
                     "vorentwurf"):
            t = time.monotonic()
            rec.setdefault("result", {}).update(run_analysis(cid, [step]))
            times[step] = round(time.monotonic() - t)
        rec["times"] = times
        conn = connect_case(cid)
        one = lambda sql, c=conn: c.execute(sql).fetchone()[0]  # noqa: E731
        rec["facts"] = one("SELECT COUNT(*) FROM facts")
        rec["facts_verified"] = one("SELECT COUNT(*) FROM facts WHERE verified=1")
        rec["timeline"] = one("SELECT COUNT(*) FROM timeline_entries WHERE excluded=0")
        rec["findings"] = [dict(r) for r in conn.execute(
            "SELECT type, claim FROM findings WHERE status='open'")]
        rec["score"] = score(name, {f["type"] for f in rec["findings"]})
        rec["llm"] = [dict(r) for r in conn.execute(
            """SELECT stage, status, COUNT(*) n, CAST(AVG(duration_ms) AS INT) avg_ms
               FROM llm_calls GROUP BY stage, status""")]
        md = [f"# {name} — {label}\n"]
        for r in conn.execute("""SELECT section_key, content_md, warnings FROM draft_sections
                                 WHERE section_key IN ('beurteilung','fragen','diagnosen')
                                 ORDER BY section_key"""):
            md.append(f"\n## {r['section_key']}\n\n{r['content_md']}\n")
            if r["warnings"] and r["warnings"] != "[]":
                md.append(f"\n_Warnungen:_ {r['warnings']}\n")
        md.append("\n## Aktenauszug\n")
        for r in conn.execute("""SELECT entry_date, title FROM timeline_entries WHERE excluded=0
                                 ORDER BY entry_date, sort"""):
            md.append(f"- {r['entry_date']}  {r['title']}\n")
        (out / f"{name}.md").write_text("".join(md), encoding="utf-8")
        conn.close()
    except Exception as e:  # one bad case must not stop the batch
        rec["error"] = repr(e)
    rec["seconds"] = round(time.monotonic() - t0)
    report.append(rec)
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False),
                                     encoding="utf-8")
    print(f"{name}: {rec['seconds']} s {rec.get('error', '')}", flush=True)
server.stop()
