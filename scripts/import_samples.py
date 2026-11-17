# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dev helper: turn each local sample folder (samples/<name>/, gitignored) into a
case in the Arbeitsliste, import its files and run OCR. Idempotent: existing test
cases are skipped. Contains no case data itself.

    uv run python scripts/import_samples.py [--samples samples] [--no-ocr]

Cases go to the normal data folder (repo cases/ in development, or GUTACHTEN_HOME).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gutachten.cases import SUPPORTED_SUFFIXES, create_case, list_cases  # noqa: E402
from gutachten.ingest.pipeline import import_file  # noqa: E402
from gutachten.ocr.runner import ocr_pending_pages  # noqa: E402

PREFIX = "Testfall (fiktiv): "


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=Path, default=ROOT / "samples")
    ap.add_argument("--no-ocr", action="store_true")
    args = ap.parse_args()
    existing = {c["title"] for c in list_cases()}
    for folder in sorted(p for p in args.samples.iterdir() if p.is_dir()):
        files = sorted(f for f in folder.iterdir() if f.suffix.lower() in SUPPORTED_SUFFIXES)
        if not files:
            continue
        title = PREFIX + folder.name
        if title in existing:
            print(f"  skip    {title} (exists)")
            continue
        cid = create_case(title, patient_ref="FIKTIV", case_type="unfall",
                          auftraggeber="Testdaten")
        pages = sum(import_file(cid, f, keep_name=False).get("pages_added", 0) for f in files)
        msg = f"  created {title}: {len(files)} Dateien, {pages} Seiten"
        if not args.no_ocr:
            r = ocr_pending_pages(cid)
            msg += f", OCR {r['ok']}/{r['total']} ({r['review']} zur Prüfung)"
        print(msg, flush=True)


if __name__ == "__main__":
    main()
