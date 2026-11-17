# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registrierung: split the page stream into logical documents and classify them.

Boundary decision per page, strongest evidence first:
  1. first page of an imported file          -> new document ('source')
  2. page marker "Seite 1 von 3" / "Seite 2/3"  -> new / continuation ('page_marker')
  3. blank page                              -> continuation (scan back sides)
  4. LLM page analysis                       -> new / continuation ('llm')
  5. LLM failed on this page                 -> new document ('fallback') — merging
     unrelated documents is worse than splitting one

Metadata of a document comes from the LLM analysis of its first page; the
document date is only kept if it is actually written on that page.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from ..dates import date_supported, normalize_iso
from ..db import database
from ..ingest.dedupe import find_duplicate_pages
from ..llm.client import JsonLLM, LlmError
from ..llm.prompts import PAGE_ANALYSIS_PROMPT, PAGE_ANALYSIS_VERSION
from ..llm.schemas import DOC_TYPES, PAGE_ANALYSIS_SCHEMA
from .common import Progress, call_llm, page_texts

PAGE_MARKER = re.compile(r"\bSeite\s+(\d{1,3})\s*(?:von|/|aus)\s*(\d{1,3})\b", re.I)
BLANK_CHARS = 15
PAGE_HEAD_CHARS = 6000
PREV_TAIL_CHARS = 600


def page_marker(text: str) -> tuple[int, int] | None:
    for m in PAGE_MARKER.finditer(text):
        n, total = int(m.group(1)), int(m.group(2))
        if 1 <= n <= total:
            return n, total
    return None


@dataclass
class _Doc:
    pages: list[dict] = field(default_factory=list)
    reason: str = "source"
    meta: dict | None = None


def _analyze(conn, case_id, llm, page, prev_text) -> dict | None:
    prompt = PAGE_ANALYSIS_PROMPT.format(
        prev_tail=prev_text[-PREV_TAIL_CHARS:] if prev_text else "(keine — erste Seite)",
        global_seq=page["global_seq"],
        page_text=page["text"][:PAGE_HEAD_CHARS],
    )
    try:
        return call_llm(
            conn, case_id, llm, stage="page_analysis", ref=f"Bl. {page['global_seq']}",
            prompt_version=PAGE_ANALYSIS_VERSION, prompt=prompt,
            schema=PAGE_ANALYSIS_SCHEMA, max_tokens=512,
        )
    except LlmError:
        return None


def run_index(
    conn: sqlite3.Connection, case_id: str, llm: JsonLLM, progress: Progress | None = None
) -> dict:
    dups = find_duplicate_pages(conn, case_id)
    dup_of = {seq: orig for seq, orig, _ in dups}
    pages = page_texts(conn, case_id)
    for p in pages:
        p["dup_of"] = dup_of.get(p["global_seq"])
    docs: list[_Doc] = []
    prev = None
    llm_calls = failures = 0
    for i, page in enumerate(pages, start=1):
        if progress:
            progress("Registrierung", i, len(pages))
        text = page["text"].strip()
        marker = page_marker(text)
        meta = None
        if prev is None or page["source_id"] != prev["source_id"]:
            new, reason = True, "source"
        elif marker:
            new, reason = marker[0] == 1, "page_marker"
        elif len(text) < BLANK_CHARS:
            new, reason = False, "blank"
        else:
            meta = _analyze(conn, case_id, llm, page, prev["text"])
            llm_calls += 1
            if meta is None:
                failures += 1
                new, reason = True, "fallback"
            else:
                new, reason = bool(meta["starts_new_document"]), "llm"

        if new:
            # first page of a document: we need its metadata
            if meta is None and len(text) >= BLANK_CHARS:
                meta = _analyze(conn, case_id, llm, page, prev["text"] if prev else "")
                llm_calls += 1
                failures += meta is None
            docs.append(_Doc(pages=[page], reason=reason, meta=meta))
        else:
            docs[-1].pages.append(page)
        prev = page

    _replace_documents(conn, case_id, docs, llm.model_id)
    database.audit(
        conn, case_id, "index_built",
        f"{len(docs)} Dokumente aus {len(pages)} Seiten, {llm_calls} LLM-Aufrufe,"
        f" {failures} fehlgeschlagen",
    )
    conn.commit()
    return {"documents": len(docs), "pages": len(pages), "llm_failures": failures,
            "duplicate_pages": len(dups)}


def _replace_documents(conn, case_id: str, docs: list[_Doc], model_id: str) -> None:
    """Re-indexing invalidates derived data: facts and pipeline timeline rows."""
    conn.execute(
        "DELETE FROM timeline_entries WHERE case_id=? AND created_by='pipeline' AND edited=0",
        (case_id,),
    )
    conn.execute("DELETE FROM facts WHERE case_id=?", (case_id,))
    conn.execute("DELETE FROM documents WHERE case_id=?", (case_id,))
    for d in docs:
        m = d.meta or {}
        first_text = d.pages[0]["text"]
        doc_type = m.get("doc_type") if m.get("doc_type") in DOC_TYPES else "sonstiges"
        title = (m.get("title") or "").strip() or "Nicht klassifiziert"
        notes = []
        doc_date = normalize_iso(m.get("doc_date"))
        if doc_date and not date_supported(doc_date, first_text):
            notes.append(f"Dokumentdatum {doc_date} nicht im Text belegt — verworfen")
            doc_date = None
        dob = normalize_iso(m.get("patient_dob"))
        if dob and not date_supported(dob, first_text):
            dob = None
        if not d.meta:
            notes.append("Seite nicht automatisch klassifiziert")
        dup = [p for p in d.pages if p.get("dup_of")]
        if dup:
            if len(dup) == len(d.pages):
                notes.append(f"Dublette von Bl. {dup[0]['dup_of']}"
                             + (f"–{dup[-1]['dup_of']}" if len(dup) > 1 else "")
                             + " (nicht ausgewertet)")
            else:
                notes.append("enthält Dubletten: " + ", ".join(
                    f"Bl. {p['global_seq']} = Bl. {p['dup_of']}" for p in dup))
        conn.execute(
            """INSERT INTO documents
               (case_id, title, doc_type, doc_date, author, institution,
                start_seq, end_seq, patient_name, patient_dob, boundary_reason,
                verify_note, prompt_version, model_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (case_id, title, doc_type, doc_date, m.get("author"), m.get("institution"),
             d.pages[0]["global_seq"], d.pages[-1]["global_seq"],
             m.get("patient_name"), dob, d.reason, "; ".join(notes) or None,
             PAGE_ANALYSIS_VERSION if d.meta else None, model_id if d.meta else None),
        )
