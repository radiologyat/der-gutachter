# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quote -> OCR block matching ("Keine Aussage ohne Fundstelle")."""
import pytest

from gutachten.cases import connect_case
from gutachten.citations import locate_quote, normalize
from gutachten.ingest.pipeline import import_file
from gutachten.ocr.runner import ocr_pending_pages

from .conftest import make_text_pdf


@pytest.fixture()
def page(case_id, text_pdf):
    import_file(case_id, text_pdf)
    ocr_pending_pages(case_id)
    conn = connect_case(case_id)
    pid = conn.execute("SELECT id FROM pages WHERE global_seq=1").fetchone()["id"]
    yield conn, pid
    conn.close()


def test_exact_quote_maps_to_its_block(page):
    conn, pid = page
    c = locate_quote(conn, [pid], "beginnende Gonarthrose (Kellgren II)")
    assert c and c.score == 1.0 and c.label == "Bl. 1 d. A."
    assert len(c.block_ids) == 1
    text = conn.execute("SELECT text FROM ocr_blocks WHERE id=?", (c.block_ids[0],)).fetchone()
    assert "Kellgren II" in text["text"]
    x0, y0, x1, y1 = c.bbox
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def test_quote_spanning_lines_returns_all_blocks(page):
    conn, pid = page
    c = locate_quote(
        conn, [pid],
        "kein Erguss. Röntgen Knie links in 2 Ebenen",
    )
    assert c and len(c.block_ids) == 2


def test_ocr_noise_still_matches(page):
    conn, pid = page
    # model "corrects" OCR or quotes with typographic differences
    c = locate_quote(conn, [pid], "Klinisch: leichte retropateIlare Krepitatlon, kein Erguss")
    assert c and 0.85 <= c.score < 1.0


def test_case_and_quote_styles_are_normalized():
    assert normalize("„Knie  LINKS“ – re.") == normalize('"knie links" - re.')


def test_invented_quote_is_rejected(page):
    conn, pid = page
    assert locate_quote(conn, [pid], "Zustand nach Kreuzbandruptur rechts 2019") is None


def test_too_short_quote_proves_nothing(page):
    conn, pid = page
    assert locate_quote(conn, [pid], "links") is None


def test_manual_text_gives_page_level_citation(page, case_id):
    conn, pid = page
    conn.execute(
        "UPDATE page_text SET text_md=?, source='manual' WHERE page_id=?",
        ("Handschriftlich: Patient stürzte am 09.10.2023 auf das linke Knie.", pid),
    )
    conn.commit()
    c = locate_quote(conn, [pid], "stürzte am 09.10.2023 auf das linke Knie")
    assert c and c.block_ids == [] and c.bbox is None and c.global_seq == 1
    # stale OCR blocks must not satisfy a quote that's no longer in the text
    assert locate_quote(conn, [pid], "beginnende Gonarthrose (Kellgren II)") is None


def test_hyphenation_across_lines(case_id, tmp_path):
    text = "Befund: deutliche Gonar-\nthrose medial links bekannt."
    pdf = make_text_pdf(tmp_path / "h.pdf", text)
    import_file(case_id, pdf)
    ocr_pending_pages(case_id)
    conn = connect_case(case_id)
    pid = conn.execute("SELECT id FROM pages").fetchone()["id"]
    c = locate_quote(conn, [pid], "deutliche Gonarthrose medial links")
    conn.close()
    assert c and c.score == 1.0 and len(c.block_ids) == 2


def test_best_page_wins_across_document(case_id, tmp_path):
    a = make_text_pdf(tmp_path / "a.pdf", "Seite eins: Anamnese ohne Befund. " * 3)
    b = make_text_pdf(tmp_path / "b.pdf", "Seite zwei: MRI zeigt Meniskusriss medial links.")
    import_file(case_id, a)
    import_file(case_id, b)
    ocr_pending_pages(case_id)
    conn = connect_case(case_id)
    ids = [r["id"] for r in conn.execute("SELECT id FROM pages ORDER BY global_seq")]
    c = locate_quote(conn, ids, "MRI zeigt Meniskusriss medial links")
    conn.close()
    assert c and c.global_seq == 2
    assert c.to_json("q")["block_id"] == c.block_ids[0]
