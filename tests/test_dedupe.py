# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page-level duplicates: same page filed twice, also scan vs. digital copy."""
from gutachten.analysis.runner import run_analysis
from gutachten.cases import connect_case
from gutachten.ingest.dedupe import find_duplicate_pages
from gutachten.ingest.pipeline import import_file
from gutachten.ocr.runner import ocr_pending_pages

from .conftest import HAS_DEU_MARK, SAMPLE_TEXT, make_scan_pdf, make_text_pdf
from .test_analysis import FakeLLM, _pdf, _rows

OTHER = SAMPLE_TEXT.replace("Arztbrief", "Verlaufsbericht").replace(
    "mediale Knieschmerzen links seit ca. 3 Monaten",
    "Schmerzen an der rechten Schulter nach Sturz beim Velofahren",
).replace("beginnende Gonarthrose (Kellgren II)", "Rotatorenmanschette intakt")


def test_text_copy_detected_and_kept(case_id, tmp_path):
    import_file(case_id, make_text_pdf(tmp_path / "a.pdf"))
    import_file(case_id, _pdf(tmp_path / "b.pdf", [OTHER, SAMPLE_TEXT]))
    ocr_pending_pages(case_id)
    conn = connect_case(case_id)
    found = find_duplicate_pages(conn, case_id)
    conn.close()
    assert [(s, o) for s, o, _ in found] == [(3, 1)]  # Bl. 2 is similar but different
    pages = _rows(case_id, "SELECT global_seq, duplicate_of FROM pages ORDER BY global_seq")
    assert [p["global_seq"] for p in pages] == [1, 2, 3]  # numbering untouched


@HAS_DEU_MARK
def test_scanned_copy_of_digital_page_detected(case_id, tmp_path):
    import_file(case_id, make_text_pdf(tmp_path / "digital.pdf"))
    import_file(case_id, make_scan_pdf(tmp_path / "scan.pdf"))
    ocr_pending_pages(case_id)
    conn = connect_case(case_id)
    found = find_duplicate_pages(conn, case_id)
    conn.close()
    assert len(found) == 1 and found[0][:2] == (2, 1)


def test_short_pages_never_called_duplicates(case_id, tmp_path):
    stub = "Vermerk Sachbearbeitung: Kopie abgelegt."
    import_file(case_id, _pdf(tmp_path / "a.pdf", [stub, stub]))
    ocr_pending_pages(case_id)
    conn = connect_case(case_id)
    assert find_duplicate_pages(conn, case_id) == []
    conn.close()


def test_duplicate_document_flagged_and_not_extracted(case_id, tmp_path):
    from .test_analysis import ARZTBRIEF_1, ARZTBRIEF_2

    pad = "\nBefundtext ohne weitere Besonderheiten, Verlauf wie beschrieben." * 2
    letter = [ARZTBRIEF_1 + pad, ARZTBRIEF_2 + pad]
    import_file(case_id, _pdf(tmp_path / "a.pdf", letter))
    # same letter again in the insurer's file, behind a cover note (file differs)
    cover = "Versicherung: Kopie des Schreibens zur Akte genommen, siehe Beilage."
    import_file(case_id, _pdf(tmp_path / "b.pdf", [cover, *letter]))
    ocr_pending_pages(case_id)
    res = run_analysis(case_id, ["index", "extract"], llm_factory=FakeLLM)
    assert res["index"]["duplicate_pages"] == 2
    docs = _rows(case_id, "SELECT start_seq, end_seq, verify_note FROM documents"
                          " ORDER BY start_seq")
    copy = next(d for d in docs if d["start_seq"] == 4)
    assert copy["end_seq"] == 5 and "Dublette von Bl. 1–2" in copy["verify_note"]
    facts = _rows(case_id, "SELECT p.global_seq FROM facts f JOIN pages p ON p.id=f.page_id")
    assert facts and all(f["global_seq"] <= 2 for f in facts)
