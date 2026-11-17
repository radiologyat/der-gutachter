# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test fixtures.

ALL TEST DATA IS FICTITIOUS AND GENERATED. "Max Muster" is a placeholder name
(like "John Doe"); institutions, dates and medical facts are invented and do not
describe any real person or case. Generated PDFs carry a visible marker line.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Point all mutable state at a temp dir BEFORE importing gutachten modules.
_TMP = Path(tempfile.mkdtemp(prefix="gutachten-test-"))
# removed after the run (each run writes ~130 MB of fictitious case data; left behind
# they filled the disk)
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)
os.environ["GUTACHTEN_HOME"] = str(_TMP)
os.environ["GUTACHTEN_LLAMA_PORT"] = "18078"
os.environ["GUTACHTEN_SETTINGS"] = str(_TMP / "settings.json")  # never the real user file

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pymupdf as fitz  # noqa: E402

from gutachten import config  # noqa: E402
from gutachten.cases import create_case  # noqa: E402

SAMPLE_TEXT = """\
Orthopädische Gemeinschaftspraxis Dr. med. Beispiel
Musterstrasse 12, 8000 Zürich

Arztbrief

Patient: Max Muster, geb. 12.03.1961
Datum: 14.03.2021

Sehr geehrter Herr Kollege,

Herr Muster berichtet über mediale Knieschmerzen links seit ca. 3 Monaten.
Klinisch: leichte retropatellare Krepitation, kein Erguss.
Röntgen Knie links in 2 Ebenen: beginnende Gonarthrose (Kellgren II).

Diagnose: M23.22 – beginnende Gonarthrose, mediale Knieschmerzen links.

Mit freundlichen Grüssen
Dr. med. Beispiel
"""


FICTION_MARK = (
    "FIKTIVES TESTDOKUMENT – automatisch generiert. "
    "Keine realen Personen, Einrichtungen oder Fälle."
)


def make_text_pdf(path: Path, text: str = SAMPLE_TEXT) -> Path:
    """Born-digital PDF with a text layer (fictitious content, visibly marked)."""
    text = f"{text}\n\n{FICTION_MARK}"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4
    page.insert_textbox(
        fitz.Rect(50, 50, 545, 800), text, fontsize=10, fontname="helv"
    )
    doc.save(path)
    doc.close()
    return path


def make_scan_pdf(path: Path, text: str = SAMPLE_TEXT) -> Path:
    """Image-only PDF — a rendered PNG inside a PDF, like a real scan."""
    tmp_txt = path.with_suffix(".txt.pdf")
    make_text_pdf(tmp_txt, text)
    src = fitz.open(tmp_txt)
    pix = src[0].get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    src.close()
    tmp_txt.unlink()

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(0, 0, 595, 842), stream=img_bytes)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def case_id() -> str:
    config.ensure_dirs()
    return create_case(
        title="Testfall Muster",
        patient_ref="MM",
        jurisdiction="CH",
        case_type="unfall",
        accident_date="2023-10-09",
        auftraggeber="Bezirksgericht Musterstadt",
    )


@pytest.fixture()
def text_pdf(tmp_path) -> Path:
    return make_text_pdf(tmp_path / "arztbrief.pdf")


@pytest.fixture()
def scan_pdf(tmp_path) -> Path:
    return make_scan_pdf(tmp_path / "scan.pdf")


HAS_DEU_MARK = pytest.mark.skipif(
    not (config.TESSDATA_DIR / "deu.traineddata").exists(),
    reason="deu traineddata not downloaded",
)
