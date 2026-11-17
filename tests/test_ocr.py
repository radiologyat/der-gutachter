# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from gutachten import config
from gutachten.cases import connect_case
from gutachten.ingest.pipeline import import_file
from gutachten.ocr.runner import ocr_pending_pages

HAS_DEU = (config.TESSDATA_DIR / "deu.traineddata").exists()


def test_pdf_text_engine_extracts(case_id, text_pdf):
    import_file(case_id, text_pdf)
    res = ocr_pending_pages(case_id)
    assert res["ok"] == 1

    conn = connect_case(case_id)
    row = conn.execute(
        """SELECT pt.text_md, pt.source, p.status FROM page_text pt
           JOIN pages p ON p.id=pt.page_id WHERE p.case_id=?""",
        (case_id,),
    ).fetchone()
    blocks = conn.execute("SELECT COUNT(*) c FROM ocr_blocks").fetchone()["c"]
    runs = conn.execute(
        "SELECT engine, status FROM ocr_runs"
    ).fetchall()
    conn.close()

    assert "Max Muster" in row["text_md"]
    assert "Gonarthrose" in row["text_md"]
    assert row["source"] == "embedded"
    assert row["status"] == "ocr_done"  # embedded text = full confidence
    assert blocks > 3
    assert runs[0]["engine"] == "pdf_text" and runs[0]["status"] == "ok"


@pytest.mark.skipif(not HAS_DEU, reason="deu traineddata not downloaded")
def test_tesseract_on_scanned_german_page(case_id, scan_pdf):
    import_file(case_id, scan_pdf)
    res = ocr_pending_pages(case_id, preferred="tesseract")
    assert res["ok"] == 1

    conn = connect_case(case_id)
    row = conn.execute(
        """SELECT pt.text_md FROM page_text pt
           JOIN pages p ON p.id=pt.page_id WHERE p.case_id=?""",
        (case_id,),
    ).fetchone()
    conn.close()
    text = row["text_md"].lower()
    assert "muster" in text or "arztbrief" in text or "orthop" in text


def test_missing_tesseract_flags_pages_instead_of_crashing(case_id, scan_pdf, monkeypatch):
    from gutachten import config
    from gutachten.ocr import tesseract_engine as te

    monkeypatch.setattr(config, "tesseract_cmd", lambda: "/nonexistent/tesseract")
    te.tesseract_version.cache_clear()
    import_file(case_id, scan_pdf)
    res = ocr_pending_pages(case_id)
    assert res["errors"] == 1
    conn = connect_case(case_id)
    run = conn.execute("SELECT engine_version, status, error FROM ocr_runs").fetchone()
    status = conn.execute("SELECT status FROM pages").fetchone()["status"]
    conn.close()
    assert run["status"] == "error" and run["engine_version"].startswith("unavailable")
    assert status == "review"
    te.tesseract_version.cache_clear()


def test_tesseract_with_spaces_and_umlauts_in_paths(tmp_path, monkeypatch):
    """Program and data folders like "C:\\Users\\Vorname Nachname" or "…\\Bühler\\…"
    must not break the text recognition (it did on Windows before 0.9.7)."""
    import shutil

    import pytest

    from gutachten import config
    from gutachten.ocr import tesseract_engine as te

    if not te.cli_available() or te._tessdata_dir() is None:
        pytest.skip("tesseract with deu data not available")
    tess = tmp_path / "Mein Ordner Ü" / "tessdata"
    tess.mkdir(parents=True)
    for f in te._tessdata_dir().glob("*.traineddata"):
        shutil.copy(f, tess / f.name)
    monkeypatch.setattr(config, "TESSDATA_DIR", tess)
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1400, 300), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 48)
    except OSError:
        font = ImageFont.load_default(size=48)
    d.text((40, 100), "Röntgen Knie links: Gonarthrose", fill="black", font=font)
    page = tmp_path / "Daten Bühler" / "P0001.png"
    page.parent.mkdir()
    img.save(page)
    res = te.TesseractEngine().ocr_image(page)
    assert "Gonarthrose" in res.text and res.blocks
