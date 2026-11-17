# SPDX-License-Identifier: AGPL-3.0-or-later
import threading

from PIL import Image

from gutachten import config
from gutachten.cases import connect_case
from gutachten.ingest.pipeline import import_file

from .conftest import make_text_pdf


def test_import_text_pdf(case_id, text_pdf):
    res = import_file(case_id, text_pdf)
    assert res["status"] == "ingested"
    assert res["pages_added"] == 1

    conn = connect_case(case_id)
    page = conn.execute("SELECT * FROM pages WHERE case_id=?", (case_id,)).fetchone()
    conn.close()
    assert page["global_seq"] == 1
    assert page["has_embedded_text"] == 1
    assert page["image_path"].endswith("P0001.png")
    assert page["phash"]


def test_import_dedupes_identical_file(case_id, text_pdf):
    import_file(case_id, text_pdf)
    res = import_file(case_id, text_pdf)
    assert res["status"] == "duplicate"
    assert res["pages_added"] == 0


def test_import_scan_pdf_has_no_text_layer(case_id, scan_pdf):
    res = import_file(case_id, scan_pdf)
    assert res["status"] == "ingested"
    conn = connect_case(case_id)
    page = conn.execute("SELECT * FROM pages WHERE case_id=?", (case_id,)).fetchone()
    conn.close()
    assert page["has_embedded_text"] == 0


def test_global_seq_is_stable_across_sources(case_id, text_pdf, scan_pdf):
    import_file(case_id, text_pdf)
    import_file(case_id, scan_pdf)
    conn = connect_case(case_id)
    seqs = [
        r["global_seq"]
        for r in conn.execute(
            "SELECT global_seq FROM pages WHERE case_id=? ORDER BY global_seq",
            (case_id,),
        )
    ]
    conn.close()
    assert seqs == [1, 2]  # "Bl. 1/2 d.A."


def _page_texts(case_id):
    from gutachten.ocr.runner import ocr_pending_pages

    ocr_pending_pages(case_id)
    conn = connect_case(case_id)
    rows = conn.execute(
        """SELECT pt.text_md FROM page_text pt JOIN pages p ON p.id=pt.page_id
           ORDER BY p.global_seq"""
    ).fetchall()
    conn.close()
    return [r["text_md"] for r in rows]


def test_same_filename_different_content_keeps_both(case_id, tmp_path):
    """Regression: 2nd 'brief.pdf' used to be rendered from the 1st file."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = make_text_pdf(tmp_path / "a" / "brief.pdf", "Erster Brief Alpha " * 5)
    b = make_text_pdf(tmp_path / "b" / "brief.pdf", "Zweiter Brief Beta " * 5)
    assert import_file(case_id, a)["status"] == "ingested"
    assert import_file(case_id, b)["status"] == "ingested"

    texts = _page_texts(case_id)
    assert "Alpha" in texts[0] and "Beta" in texts[1]
    inbox = sorted(p.name for p in (config.case_dir(case_id) / "inbox").iterdir())
    assert len(inbox) == 2 and "brief.pdf" in inbox


def test_multipage_tiff_imports_every_frame(case_id, tmp_path):
    tif = tmp_path / "scan.tif"
    frames = [Image.new("RGB", (200, 280), c) for c in ("white", "gray", "black")]
    frames[0].save(tif, save_all=True, append_images=frames[1:])
    res = import_file(case_id, tif)
    assert res["pages_added"] == 3
    conn = connect_case(case_id)
    rows = conn.execute("SELECT page_no, global_seq FROM pages ORDER BY global_seq").fetchall()
    conn.close()
    assert [(r["page_no"], r["global_seq"]) for r in rows] == [(1, 1), (2, 2), (3, 3)]


def test_text_file_becomes_text_page(case_id, tmp_path):
    notes = tmp_path / "notiz.txt"
    notes.write_text("Fiktive Notiz: Kniebeschwerden links seit dem Ereignis, Testfall.")
    r = import_file(case_id, notes)
    assert r["status"] == "ingested" and r["converted"] == "text" and r["pages_added"] == 1
    conn = connect_case(case_id)
    page = conn.execute("SELECT has_embedded_text FROM pages").fetchone()
    conn.close()
    assert page[0] == 1  # text layer, no OCR needed
    assert (config.case_dir(case_id) / "inbox" / "notiz.txt").exists()  # original kept


def test_docx_rtf_eml_and_unknown_are_imported(case_id, tmp_path):
    from email.message import EmailMessage

    from docx import Document

    d = Document()
    d.add_paragraph("Fiktiver Arztbrief Testfall: Distorsion Knie rechts.")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Diagnose", "Distorsion"
    d.save(tmp_path / "brief.docx")
    (tmp_path / "bericht.rtf").write_text(
        r"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0 Fiktiver Bericht: Kn\'e4ul\par Zeile 2}")
    m = EmailMessage()
    m["From"], m["Subject"] = "praxis@example.invalid", "Fiktive Zuweisung Testfall"
    m.set_content("Bitte um Beurteilung, fiktiver Testfall.")
    m.add_attachment(b"Anhang Testfall fiktiv mit genug Text fuer eine Seite.",
                     maintype="text", subtype="plain", filename="anhang.txt")
    (tmp_path / "mail.eml").write_bytes(bytes(m))
    (tmp_path / "daten.xyz").write_bytes(b"\x00\x01")
    assert import_file(case_id, tmp_path / "brief.docx")["converted"] == "docx"
    assert import_file(case_id, tmp_path / "bericht.rtf")["converted"] == "rtf"
    r = import_file(case_id, tmp_path / "mail.eml")
    assert r["converted"] == "eml" and r["attachments"][0]["status"] == "ingested"
    assert import_file(case_id, tmp_path / "daten.xyz")["converted"] == "placeholder"
    assert import_file(case_id, tmp_path / "Thumbs.db")["status"] == "skipped"


def test_rtf_reader():
    from gutachten.ingest.convert import rtf_text

    assert rtf_text(r"{\rtf1{\fonttbl{\f0 Arial;}}M\'fcller\par Knie \u8364?}") == \
        "Müller\nKnie €"


def test_corrupt_pdf_leaves_no_pages_or_temp_files(case_id, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 not really a pdf")
    assert import_file(case_id, bad)["status"] == "error"
    pages_dir = config.case_dir(case_id) / "pages"
    assert list(pages_dir.iterdir()) == []
    conn = connect_case(case_id)
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0
    conn.close()


def test_concurrent_imports_get_unique_sequential_seqs(case_id, tmp_path):
    files = [
        make_text_pdf(tmp_path / f"d{i}.pdf", f"Dokument Nummer {i} " * 5) for i in range(6)
    ]
    errors: list[Exception] = []

    def run(p):
        try:
            import_file(case_id, p, keep_name=False)
        except Exception as e:  # pragma: no cover - surfaced below
            errors.append(e)

    threads = [threading.Thread(target=run, args=(f,)) for f in files]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    conn = connect_case(case_id)
    seqs = [r[0] for r in conn.execute("SELECT global_seq FROM pages ORDER BY global_seq")]
    conn.close()
    assert seqs == list(range(1, 7))


def test_scan_with_invisible_text_layer_is_ocrd_not_trusted(case_id, tmp_path):
    """Scanner software often adds a (poor) OCR text layer. A full-page image +
    text layer must not be taken as born-digital text at confidence 1.0."""
    import pymupdf as fitz

    from .conftest import make_scan_pdf

    pdf = make_scan_pdf(tmp_path / "scan.pdf")
    doc = fitz.open(pdf)
    doc[0].insert_textbox(fitz.Rect(50, 50, 545, 800), "scannerocr Mvster Arztbrlef " * 10,
                          fontsize=10, render_mode=3)  # invisible text
    out = tmp_path / "scan_layer.pdf"
    doc.save(out)
    doc.close()

    import_file(case_id, out)
    conn = connect_case(case_id)
    page = conn.execute("SELECT * FROM pages").fetchone()
    conn.close()
    assert page["embedded_chars"] >= 40
    assert page["image_coverage"] > 0.9
    assert page["has_embedded_text"] == 0  # -> OCR from the image


def test_born_digital_page_with_logo_trusts_text_layer(case_id, tmp_path):
    import io

    import pymupdf as fitz

    pdf = make_text_pdf(tmp_path / "digital.pdf")
    doc = fitz.open(pdf)
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), "navy").save(buf, format="PNG")
    doc[0].insert_image(fitz.Rect(450, 20, 560, 70), stream=buf.getvalue())  # small logo
    out = tmp_path / "digital_logo.pdf"
    doc.save(out)
    doc.close()

    import_file(case_id, out)
    conn = connect_case(case_id)
    page = conn.execute("SELECT * FROM pages").fetchone()
    conn.close()
    assert 0 < page["image_coverage"] < 0.1
    assert page["has_embedded_text"] == 1
