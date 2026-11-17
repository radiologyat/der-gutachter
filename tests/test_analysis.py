# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 2 pipeline against a scripted fake LLM.

ALL DOCUMENTS BELOW ARE FICTITIOUS AND GENERATED (placeholder names, invented
institutions, dates and findings); generated PDFs carry a visible marker line.

The fake deliberately lies in places — invented quotes, wrong dates, a made-up
Beweisfrage — to prove the verification gates catch it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf as fitz
import pytest

from gutachten.analysis.common import LlmUnavailable
from gutachten.analysis.cover import decide_suggestion, list_suggestions
from gutachten.analysis.extract import chunk_pages
from gutachten.analysis.runner import run_analysis
from gutachten.analysis.segment import page_marker
from gutachten.cases import connect_case, get_case
from gutachten.ingest.pipeline import import_file
from gutachten.llm.client import LlmError
from gutachten.ocr.runner import ocr_pending_pages

AUFTRAG = """\
Bezirksgericht Musterstadt
Geschäfts-Nr. CG210045
Gutachtenauftrag
In Sachen Max Muster, geb. 12.03.1961,
betreffend Unfall vom 09.10.2023.
Das Gutachten ist bis 31.01.2027 einzureichen.
Beweisfragen:
1. Welche Gesundheitsschäden liegen am linken Knie vor?
2. Sind die Beschwerden unfallkausal?
"""

ARZTBRIEF_1 = """\
Orthopädie Dr. med. Beispiel, Zürich
Arztbrief vom 14.03.2021
Patient: Max Muster, geb. 12.03.1961
Röntgen Knie links in 2 Ebenen:
beginnende Gonarthrose (Kellgren II).
Seite 1 von 2
"""
ARZTBRIEF_2 = """\
Procedere: Physiotherapie 9x verordnet.
Kontrolle in 3 Monaten.
Mit freundlichen Grüssen
Dr. med. Beispiel
Seite 2 von 2
"""
MRI_1 = """\
Radiologie Institut Seeblick
MRI Knie links vom 20.10.2023
Befund: horizontale Meniskusläsion
im Hinterhorn medial links.
"""
MRI_2 = """\
Beurteilung: frische Meniskusläsion medial.
Kein Knochenmarködem lateral.
Dr. med. Radiologe
"""
OP = """\
Kantonsspital Musterstadt
Operationsbericht vom 15.11.2023
Eingriff: Arthroskopie Knie links,
Teilmeniskektomie medial.
"""
VERLAUF = """\
Kantonsspital Musterstadt
Verlaufsbericht vom 02.02.2024
Status nach Arthroskopie Knie links
am 15.11.2023, gute Beweglichkeit.
"""


def _pdf(path: Path, pages: list[str]) -> Path:
    from .conftest import FICTION_MARK

    doc = fitz.open()
    for text in pages:
        text = f"{text}\n{FICTION_MARK}"
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(fitz.Rect(50, 50, 545, 800), text, fontsize=11, fontname="helv")
    doc.save(path)
    doc.close()
    return path


def _section(prompt: str, marker: str) -> str:
    m = re.search(marker + r".*?<<<\n(.*?)\n>>>", prompt, re.S)
    return m.group(1) if m else ""


class FakeLLM:
    model_id = "fake-qwen"

    def __init__(self, fail_pages: set[str] = frozenset()):
        self.calls: list[tuple[str, str]] = []
        self.fail_pages = fail_pages

    def chat_json(self, messages, schema, schema_name="response", max_tokens=4096):
        prompt = messages[-1]["content"]
        self.calls.append((schema_name, prompt))
        return getattr(self, f"_{schema_name}")(prompt)

    # ---- page analysis
    def _page_analysis(self, prompt):
        page = _section(prompt, "AKTUELLE Seite")
        seq = re.search(r"Bl\. (\d+) d\. A\.", prompt).group(1)
        if seq in self.fail_pages:
            raise LlmError("simulated failure")
        first = page.splitlines()[:3]
        head = " ".join(first)

        def meta(new, typ, title, date=None, author=None, inst=None):
            return {"starts_new_document": new, "doc_type": typ, "title": title,
                    "doc_date": date, "author": author, "institution": inst,
                    "patient_name": "Max Muster" if "Muster" in page else None,
                    "patient_dob": "1961-03-12" if "12.03.1961" in page else None}

        if "Gutachtenauftrag" in head:
            return meta(True, "korrespondenz", "Gutachtenauftrag", None, None,
                        "Bezirksgericht Musterstadt")
        if "Arztbrief" in head:
            return meta(True, "arztbrief", "Arztbrief Orthopädie", "2021-03-14",
                        "Dr. med. Beispiel")
        if "MRI" in head:
            # lies about the date: 21.10. is not on the page -> must be dropped
            return meta(True, "radiologie", "MRI Knie links", "2023-10-21")
        if "Operationsbericht" in head:
            return meta(True, "op_bericht", "Operationsbericht", "2023-11-15")
        if "Verlaufsbericht" in head:
            return meta(True, "arztbrief", "Verlaufsbericht", "2024-02-02")
        return meta(False, "sonstiges", "Fortsetzung")

    # ---- facts
    def _fact_extract(self, prompt):
        def f(date, page, cat, title, quote, lat="links", caus="unklar", icd=None, end=None):
            return {"fact_date": date, "fact_date_end": end, "page": page, "event_category": cat,
                    "causality": caus, "body_region": "Knie", "laterality": lat,
                    "icd10": icd, "title": title, "summary": title, "quote": quote}

        seqs = [int(s) for s in re.findall(r"=== Bl\. (\d+) d\. A\. ===", prompt)]
        p = seqs[0] if seqs else None
        # match on the document line only — the prompt's own examples mention e.g. "MRI"
        doc = re.search(r"^Dokument: (.*)$", prompt, re.M).group(1)
        if "Arztbrief Orthopädie" in doc:
            return {"facts": [
                f("2021-03-14", p, "vorbefund", "Gonarthrose links",
                  "beginnende Gonarthrose (Kellgren II).", caus="vorschaden", icd="M17.1"),
                # invented quote -> unverified
                f("2021-03-14", p, "op", "Kreuzbandplastik rechts",
                  "Zustand nach Kreuzbandplastik rechts 2015.", lat="rechts"),
                # real quote, invented date -> unverified
                f("2020-01-01", p, "konservativ", "Physiotherapie",
                  "Procedere: Physiotherapie 9x verordnet."),
            ]}
        if "MRI Knie links" in doc:
            # doc date was dropped (fake lied about it) -> the date must be in the quote
            return {"facts": [f("2023-10-20", p, "diagnostik", "Meniskusläsion medial links",
                                "MRI Knie links vom 20.10.2023 Befund: horizontale "
                                "Meniskusläsion im Hinterhorn medial links.")]}
        if "Operationsbericht" in doc:
            return {"facts": [f("2023-11-15", p, "op", "Arthroskopie Knie links",
                                "Eingriff: Arthroskopie Knie links, Teilmeniskektomie medial.",
                                caus="unfallkausal")]}
        if "Verlaufsbericht" in doc:
            return {"facts": [
                # same event as the OP-Bericht, other source -> merged in the timeline
                f("2023-11-15", p, "op", "Arthroskopie Knie links",
                  "Status nach Arthroskopie Knie links am 15.11.2023", caus="unfallkausal"),
                f("2024-02-02", p, "konservativ", "Verlaufskontrolle",
                  "gute Beweglichkeit."),
            ]}
        return {"facts": []}

    # ---- cover
    def _checks_ki(self, prompt):
        """One good issue, plus three that the gate must drop (unknown entry,
        invented date, judgement)."""
        refs = re.findall(r"^\[(E\d+)\]", prompt, re.M)
        return {"issues": [
            {"type": "vorschaden_abgrenzung", "severity": "medium",
             "claim": "Dieselbe Region wurde vor dem Ereignis bereits behandelt (E1).",
             "relevance": "Abgrenzung Vorzustand für die Kausalitätsfrage.",
             "refs_a": refs[:1], "refs_b": refs[-1:]},
            {"type": "fehlende_unterlage", "severity": "low", "claim": "Bilder fehlen.",
             "relevance": "x", "refs_a": ["E999"], "refs_b": []},
            {"type": "widerspruch", "severity": "high",
             "claim": "Am 01.01.2019 wurde etwas anderes berichtet.", "relevance": "x",
             "refs_a": refs[:1], "refs_b": []},
            {"type": "kausalkette", "severity": "medium",
             "claim": "Die Operation ist überwiegend wahrscheinlich unfallkausal.",
             "relevance": "x", "refs_a": refs[:1], "refs_b": []},
        ]}

    def _cover(self, prompt):
        return {
            "auftraggeber": {"value": "Bezirksgericht Musterstadt",
                             "quote": "Bezirksgericht Musterstadt"},
            "aktenzeichen": {"value": "CG210045", "quote": "Geschäfts-Nr. CG210045"},
            "patient_name": {"value": "Max Muster", "quote": "In Sachen Max Muster"},
            "patient_dob": {"value": "1961-03-12", "quote": "geb. 12.03.1961"},
            "accident_date": {"value": "2023-10-09", "quote": "betreffend Unfall vom 09.10.2023."},
            "deadlines": [{"kind": "frist", "date": "2027-01-31", "label": "Abgabe Gutachten",
                           "quote": "Das Gutachten ist bis 31.01.2027 einzureichen."}],
            "questions": [
                "Welche Gesundheitsschäden liegen am linken Knie vor?",
                "Sind die Beschwerden unfallkausal?",
                "Liegt eine dauernde Arbeitsunfähigkeit vor?",  # not in the Auftrag
            ],
        }


@pytest.fixture()
def akte(case_id, tmp_path) -> str:
    """Bl. 1 Auftrag | Bl. 2-3 Arztbrief (Seite x von 2) | Bl. 4-5 MRI (2 pages, no
    marker) — same file as Arztbrief | Bl. 6 OP + Bl. 7 Verlauf in one file."""
    import_file(case_id, _pdf(tmp_path / "auftrag.pdf", [AUFTRAG]))
    import_file(case_id, _pdf(tmp_path / "akte1.pdf", [ARZTBRIEF_1, ARZTBRIEF_2, MRI_1, MRI_2]))
    import_file(case_id, _pdf(tmp_path / "akte2.pdf", [OP, VERLAUF]))
    ocr_pending_pages(case_id)
    return case_id


def _rows(case_id, sql, *args):
    conn = connect_case(case_id)
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


# ------------------------------------------------------------------ segmentation

def test_page_marker_parsing():
    assert page_marker("… Seite 2 von 3 …") == (2, 3)
    assert page_marker("Seite 1/4") == (1, 4)
    assert page_marker("Seite 5 von 3") is None
    assert page_marker("Seitenband links") is None


def test_index_builds_documents_with_rules_and_llm(akte):
    llm = FakeLLM()
    res = run_analysis(akte, ["index"], llm_factory=lambda: llm)
    assert res["index"]["documents"] == 5
    docs = _rows(akte, "SELECT * FROM documents ORDER BY start_seq")
    got = [(d["start_seq"], d["end_seq"], d["doc_type"], d["boundary_reason"]) for d in docs]
    assert got == [
        (1, 1, "korrespondenz", "source"),
        (2, 3, "arztbrief", "source"),     # Bl. 3 joined via "Seite 2 von 2"
        (4, 5, "radiologie", "llm"),       # LLM: new doc at Bl. 4, continuation Bl. 5
        (6, 6, "op_bericht", "source"),
        (7, 7, "arztbrief", "llm"),
    ]
    # Bl. 3 was decided by the page marker alone — no LLM call for it
    analysed = {re.search(r"Bl\. (\d+) d\. A\.", p).group(1)
                for name, p in llm.calls if name == "page_analysis"}
    assert "3" not in analysed
    assert docs[1]["doc_date"] == "2021-03-14"
    assert docs[1]["patient_dob"] == "1961-03-12"
    # MRI date claimed by the model (21.10.) is not on the page -> dropped with a note
    assert docs[2]["doc_date"] is None and "nicht im Text belegt" in docs[2]["verify_note"]
    assert get_case(akte)["stage"] == "index"
    n_logged = _rows(akte, "SELECT COUNT(*) n FROM llm_calls WHERE stage='page_analysis'")
    assert n_logged[0]["n"] == len(analysed)


def test_llm_failure_on_a_page_splits_rather_than_merges(akte):
    run_analysis(akte, ["index"], llm_factory=lambda: FakeLLM(fail_pages={"5"}))
    docs = _rows(akte, "SELECT start_seq, end_seq, boundary_reason, verify_note"
                       " FROM documents ORDER BY start_seq")
    assert (5, 5, "fallback") == tuple(list(docs[3].values())[:3])
    assert "nicht automatisch klassifiziert" in docs[3]["verify_note"]
    errors = _rows(akte, "SELECT ref FROM llm_calls WHERE status='error'")
    assert errors and errors[0]["ref"] == "Bl. 5"


# ------------------------------------------------------------------ extraction

def test_extract_verifies_quotes_and_dates(akte):
    run_analysis(akte, ["index", "extract"], llm_factory=FakeLLM)
    facts = {f["title"]: f for f in _rows(akte, "SELECT * FROM facts")}
    assert facts["Gonarthrose links"]["verified"] == 1
    assert json.loads(facts["Gonarthrose links"]["block_ids"])
    assert facts["Gonarthrose links"]["prompt_version"] == "fact-extract-v4"
    assert facts["Gonarthrose links"]["model_id"] == "fake-qwen"

    invented = facts["Kreuzbandplastik rechts"]
    assert invented["verified"] == 0 and "Zitat nicht" in invented["verify_note"]

    wrong_date = facts["Physiotherapie"]
    assert wrong_date["verified"] == 0 and "2020-01-01" in wrong_date["verify_note"]
    # date only elsewhere in the document is not enough — must be in the quote / doc date
    assert facts["Meniskusläsion medial links"]["verified"] == 1
    # the quote itself was found on Bl. 3 (page 2 of the Arztbrief)
    page = _rows(akte, "SELECT global_seq FROM pages WHERE id=?", wrong_date["page_id"])
    assert page[0]["global_seq"] == 3
    assert get_case(akte)["stage"] == "analysis"


def test_chunking_keeps_pages_whole():
    pages = [{"id": i, "global_seq": i, "text": "x" * 10_000} for i in range(1, 6)]
    chunks = chunk_pages(pages, limit=25_000)
    assert [[p["id"] for p in c] for c in chunks] == [[1, 2], [3, 4], [5]]


# ------------------------------------------------------------------ timeline

def test_timeline_merges_same_event_and_excludes_unverified(akte):
    res = run_analysis(akte, ["index", "extract", "timeline"], llm_factory=FakeLLM)
    assert res["timeline"]["facts_used"] == 5
    entries = _rows(akte, "SELECT * FROM timeline_entries ORDER BY entry_date, sort")
    titles = [(e["entry_date"], e["title"]) for e in entries]
    assert titles == [
        ("2021-03-14", "Gonarthrose links"),
        ("2023-10-20", "Meniskusläsion medial links"),
        ("2023-11-15", "Arthroskopie Knie links"),
        ("2024-02-02", "Verlaufskontrolle"),
    ]
    op = entries[2]
    cits = json.loads(op["citations"])
    assert sorted(c["global_seq"] for c in cits) == [6, 7]  # OP-Bericht + Verlaufsbericht
    assert all(c["bbox"] and c["block_ids"] for c in cits)
    assert op["causality"] == "unfallkausal"
    assert not any("Kreuzband" in t for _, t in titles)


def test_rebuild_keeps_user_edited_entries(akte):
    run_analysis(akte, ["index", "extract", "timeline"], llm_factory=FakeLLM)
    conn = connect_case(akte)
    conn.execute("UPDATE timeline_entries SET edited=1, title='Vom Gutachter bearbeitet'"
                 " WHERE entry_date='2024-02-02'")
    conn.commit()
    conn.close()
    run_analysis(akte, ["timeline"])
    titles = [e["title"] for e in _rows(akte, "SELECT title FROM timeline_entries")]
    assert "Vom Gutachter bearbeitet" in titles
    # the edited row replaces the event: no second pipeline row for the same facts
    assert "Verlaufskontrolle" not in titles and len(titles) == 4


# ------------------------------------------------------------------ cover

def test_cover_suggestions_verified_and_applied_on_accept(akte):
    run_analysis(akte, ["cover"], llm_factory=FakeLLM)
    sugg = list_suggestions(akte)
    by = {(s["kind"], json.dumps(s["payload"], ensure_ascii=False)): s for s in sugg}
    q_fake = next(s for s in sugg if "Arbeitsunfähigkeit" in s["payload"].get("text", ""))
    assert q_fake["verified"] == 0 and q_fake["citation"] is None
    accident = next(s for s in sugg if s["payload"].get("field") == "accident_date")
    assert accident["verified"] == 1 and accident["citation"]["global_seq"] == 1
    assert len(by) == len(sugg) == 9

    # nothing applied until accepted
    case = get_case(akte)
    assert case["auftraggeber"] == "Bezirksgericht Musterstadt"  # fixture value, unchanged
    for s in sugg:
        decide_suggestion(akte, s["id"], accept=s["verified"] == 1)
    case = get_case(akte)
    assert case["accident_date"] == "2023-10-09"
    assert case["patient_dob"] == "1961-03-12"
    assert "Aktenzeichen: CG210045" in case["notes"]
    assert case["next_date"]["date"] == "2027-01-31"
    qs = _rows(akte, "SELECT text FROM questions ORDER BY ord")
    assert [q["text"] for q in qs] == [
        "Welche Gesundheitsschäden liegen am linken Knie vor?",
        "Sind die Beschwerden unfallkausal?",
    ]
    actions = [r["action"] for r in _rows(akte, "SELECT action FROM audit_log")]
    assert actions.count("suggestion_accepted") == 8
    assert actions.count("suggestion_rejected") == 1


def test_missing_model_gives_clear_error(akte, monkeypatch):
    from gutachten import config

    monkeypatch.setattr(config, "EXTRACT_MODEL", None)
    monkeypatch.setattr(config, "EXTRACT_MODEL_DIR", Path("/nonexistent"))
    with pytest.raises(LlmUnavailable, match="Einrichtung"):
        run_analysis(akte, ["index"])


def test_date_elsewhere_in_document_does_not_verify(akte):
    """Regression (real-model eval): a diagnosis was dated with an unrelated date
    that merely appeared elsewhere in the same document."""
    from gutachten.analysis.extract import _verify

    conn = connect_case(akte)
    run_analysis(akte, ["index"], llm_factory=FakeLLM)
    page = _rows(akte, "SELECT id, global_seq FROM pages WHERE global_seq=7")[0]
    text = _rows(akte, "SELECT text_md FROM page_text WHERE page_id=?", page["id"])[0]
    chunk = [{"id": page["id"], "global_seq": 7, "text": text["text_md"]}]
    fact = {"fact_date": "2023-11-15", "page": 7, "quote": "gute Beweglichkeit."}
    _cit, _d, _e, note = _verify(conn, fact, chunk, doc_date="2024-02-02")
    assert note and "nicht in der Textstelle" in note  # 15.11.2023 is on the page, not in quote
    fact["fact_date_end"] = "2024-12-31"  # end date not in quote -> dropped, fact kept
    fact["fact_date"] = "2024-02-02"
    _cit, d, e, note = _verify(conn, fact, chunk, doc_date="2024-02-02")
    conn.close()
    assert note is None and d == "2024-02-02" and e is None


def test_same_document_same_day_details_fold_into_one_row(case_id):
    """Eval 2: MRI 'Befund' and 'Beurteilung' became two rows."""
    from gutachten.analysis.timeline import build_timeline

    conn = connect_case(case_id)
    conn.execute("INSERT INTO sources (id, case_id, filename, sha256) VALUES (1, ?, 'x', 'h')",
                 (case_id,))
    conn.execute("INSERT INTO pages (id, case_id, source_id, page_no, global_seq)"
                 " VALUES (1, ?, 1, 1, 1)", (case_id,))
    conn.executemany("INSERT INTO documents (id, case_id, title, start_seq, end_seq)"
                     " VALUES (?, ?, ?, 1, 1)", [(1, case_id, "MRI"), (2, case_id, "Brief")])
    rows = [  # doc, title, category
        (1, "MRI Knie links: Innenmeniskusriss", "diagnostik"),
        (1, "Knochenmarködem medial", "diagnostik"),
        (2, "Kontrolle Hausarzt", "diagnostik"),   # other document, other event
    ]
    for doc, title, cat in rows:
        conn.execute(
            "INSERT INTO facts (case_id, document_id, page_id, fact_date, event_category,"
            " causality, laterality, title, summary, quote, verified)"
            " VALUES (?,?,1,'2023-10-20',?,'unklar','links',?,?, 'q', 1)",
            (case_id, doc, cat, title, title),
        )
    conn.commit()
    build_timeline(conn, case_id)
    entries = _rows(case_id, "SELECT title, summary, citations FROM timeline_entries ORDER BY id")
    conn.close()
    assert [e["title"] for e in entries] == ["MRI Knie links: Innenmeniskusriss",
                                             "Kontrolle Hausarzt"]
    assert "Knochenmarködem medial" in entries[0]["summary"]
    assert len(json.loads(entries[0]["citations"])) == 2


def test_same_event_reworded_in_other_document_merges():
    from gutachten.analysis.timeline import _same_event

    entry = {"entry_date": "2023-11-15", "category": "op", "laterality": "links",
             "doc_ids": {1}, "icd10s": set(),
             "title": "Arthroskopie Knie links, Teilmeniskektomie medial"}
    fact = {"fact_date": "2023-11-15", "event_category": "op", "laterality": "links",
            "document_id": 2, "icd10": None, "title": "Teilmeniskektomie medial links"}
    assert _same_event(entry, fact)
    assert not _same_event(entry, {**fact, "title": "Knie links"})  # too generic
    assert not _same_event(entry, {**fact, "fact_date": "2023-11-16"})


def test_unusable_date_does_not_invalidate_quoted_fact(akte):
    """Regression (real model): fact_date 'vor 2024-01-22' made a correctly quoted
    prior-condition statement 'unbelegt'."""
    from gutachten.analysis.extract import _verify

    run_analysis(akte, ["index"], llm_factory=FakeLLM)
    conn = connect_case(akte)
    page = _rows(akte, "SELECT id FROM pages WHERE global_seq=2")[0]
    text = _rows(akte, "SELECT text_md FROM page_text WHERE page_id=?", page["id"])[0]
    chunk = [{"id": page["id"], "global_seq": 2, "text": text["text_md"]}]
    fact = {"fact_date": "vor 2023-10-09", "page": 2,
            "quote": "beginnende Gonarthrose (Kellgren II)."}
    cit, fdate, _end, note = _verify(conn, fact, chunk, doc_date=None)
    conn.close()
    assert cit is not None and fdate is None and note is None


def test_assignment_type_from_client():
    from gutachten.analysis.cover import infer_case_type

    assert infer_case_type("IV-Stelle des Kantons Bern") == "invaliditaet"
    assert infer_case_type("Office AI du canton de Vaud") == "invaliditaet"
    assert infer_case_type("SUVA Luzern") == "unfall"
    assert infer_case_type("ALPENLAND UNFALLVERSICHERUNG AG") == "unfall"
    assert infer_case_type("Sozialversicherungsgericht Zürich") == "unfall"
    assert infer_case_type("Bezirksgericht Musterstadt") == "haftpflicht"
    assert infer_case_type("Advokatur Muster") == "haftpflicht"
    assert infer_case_type("Dr. med. Beispiel") is None


def test_assignment_pages_found_by_words_or_chosen(akte):  # noqa: F811
    from gutachten.analysis.cover import assignment_pages, assignment_score
    from gutachten.cases import set_pipeline

    assert assignment_score("Gutachtenauftrag … Beweisfragen: 1. …") == 2
    assert assignment_score("Röntgen Knie links") == 0
    c = connect_case(akte)
    auto = assignment_pages(c, akte)
    c.close()
    assert auto and auto[0] == 1  # the fictitious file starts with the assignment
    set_pipeline(akte, cover_pages=[2, 3])
    c = connect_case(akte)
    assert assignment_pages(c, akte) == [2, 3]
    c.close()


def test_same_day_imaging_findings_are_not_merged(akte):  # noqa: F811
    from gutachten.analysis.extract import _merge_duplicate_facts

    run_analysis(akte, ["index"], llm_factory=FakeLLM)
    c = connect_case(akte)
    doc = c.execute("SELECT id FROM documents LIMIT 1").fetchone()[0]
    page = c.execute("SELECT id FROM pages LIMIT 1").fetchone()[0]
    for title in ("Röntgen Knie links: Gonarthrose", "MRT Knie links: Meniskusriss",
                  "Distorsion Knie links", "Knieverletzung links beim Sturz"):
        cat = "diagnostik" if title[:3] in ("Rön", "MRT") else "trauma"
        c.execute("INSERT INTO facts (case_id, document_id, page_id, fact_date, title,"
                  " event_category, body_region, laterality, verified, quote)"
                  " VALUES (?,?,?,?,?,?,?,?,1,'x')",
                  (akte, doc, page, "2024-03-02", title, cat, "knie", "links"))
    merged = _merge_duplicate_facts(c, akte)
    titles = [r[0] for r in c.execute("SELECT title FROM facts WHERE fact_date='2024-03-02'")]
    c.close()
    assert "Röntgen Knie links: Gonarthrose" in titles and "MRT Knie links: Meniskusriss" in titles
    assert merged == 1  # the two trauma phrasings of the same event


def test_question_numbering_from_letter_is_dropped():
    from gutachten.analysis.cover import ENUM

    assert ENUM.sub("", "1. Welche Diagnosen?") == "Welche Diagnosen?"
    assert ENUM.sub("", "b) Ist die KTEP kausal?") == "Ist die KTEP kausal?"
    assert ENUM.sub("", "2024 wurde operiert?") == "2024 wurde operiert?"
