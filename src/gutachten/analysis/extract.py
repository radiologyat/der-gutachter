# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fakt-Extraktion per document, with mandatory citation verification.

The LLM proposes facts with a verbatim quote; a fact is `verified` only if
  - its quote is found in the document's pages (citations.locate_quote), and
  - its date (if any) is written in the document text or equals the verified
    document date.
Unverified facts are stored with the reason (`verify_note`) so the user can
see what the model claimed — they never reach the Aktenauszug.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from difflib import SequenceMatcher

from ..citations import locate_quote
from ..dates import date_supported, normalize_iso
from ..db import database
from ..llm.client import JsonLLM, LlmError
from ..llm.prompts import FACT_EXTRACT_PROMPT, FACT_EXTRACT_VERSION
from ..llm.schemas import FACT_EXTRACTION_SCHEMA
from .common import Progress, call_llm

# ~4 chars/token: 8k chars ≈ 2k tokens input; smaller chunks raise fact recall —
# the model returns only a handful of facts per call regardless of input size
CHUNK_CHARS = int(os.environ.get("GUTACHTEN_CHUNK_CHARS", "8000"))

CATEGORIES = set(
    FACT_EXTRACTION_SCHEMA["properties"]["facts"]["items"]["properties"]
    ["event_category"]["enum"]
)
CAUSALITY = {"vorschaden", "unfallkausal", "kombiniert", "unklar", "none"}


def causality_for(label: str | None, fact_date: str | None, accident: str | None) -> str:
    """The model's label, constrained by date logic: without an accident date no
    causality can be judged; anything documented before the accident cannot be a
    consequence of it (an earlier injury is a Vorzustand relative to this event)."""
    if not accident:
        return "unklar"
    label = label if label in CAUSALITY else "unklar"
    if (fact_date and fact_date < accident and not accident.startswith(fact_date)
            and label in ("unfallkausal", "kombiniert")):
        return "vorschaden"
    return label
LATERALITY = {"links", "rechts", "beidseits", "na"}


def _doc_pages(conn, doc) -> list[dict]:
    return [
        dict(r) for r in conn.execute(
            """SELECT p.id, p.global_seq, COALESCE(pt.text_md,'') AS text
               FROM pages p LEFT JOIN page_text pt ON pt.page_id=p.id
               WHERE p.case_id=? AND p.global_seq BETWEEN ? AND ?
                 AND p.duplicate_of IS NULL  -- copies add no facts, only duplicate rows
               ORDER BY p.global_seq""",
            (doc["case_id"], doc["start_seq"], doc["end_seq"]),
        )
    ]


def chunk_pages(pages: list[dict], limit: int = CHUNK_CHARS) -> list[list[dict]]:
    """Group consecutive pages into chunks under `limit` chars (a single huge
    page becomes its own chunk, truncated by the caller's prompt budget)."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for p in pages:
        n = len(p["text"]) + 30
        if cur and size + n > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def _render(chunk: list[dict]) -> str:
    return "\n\n".join(
        f"=== Bl. {p['global_seq']} d. A. ===\n{p['text'][:CHUNK_CHARS]}" for p in chunk
    )


def _date_ok(iso: str, quote: str, doc_date: str | None) -> bool:
    """A fact's date must be written in its own quote, or be the (verified)
    document date. A date that merely occurs elsewhere in the document does not
    count — that is how a diagnosis gets mis-dated to an unrelated event."""
    return date_supported(iso, quote) or (doc_date is not None and iso == doc_date)


def _verify(conn, fact: dict, chunk: list[dict], doc_date: str | None):
    """-> (citation | None, fact_date | None, fact_date_end | None, note | None)"""
    by_seq = {p["global_seq"]: p for p in chunk}
    claimed = by_seq.get(fact.get("page"))
    order = ([claimed["id"]] if claimed else []) + [
        p["id"] for p in chunk if not claimed or p["id"] != claimed["id"]
    ]
    quote = fact.get("quote") or ""
    cit = locate_quote(conn, order, quote)
    notes = []
    if cit is None:
        notes.append("Zitat nicht in der Akte gefunden")

    raw_date = fact.get("fact_date")
    fdate = normalize_iso(raw_date)
    # An unusable date ("vor 2024-01-22") is dropped; it must not invalidate a fact
    # whose quote is in the Akte. A date that IS stated must be supported.
    if fdate and not _date_ok(fdate, quote, doc_date):
        notes.append(f"Datum {fdate} nicht in der Textstelle belegt")

    # End of a period: kept only if it is written in the quote; never rejects the fact.
    fend = normalize_iso(fact.get("fact_date_end"))
    if fend and (not fdate or fend < fdate or not date_supported(fend, quote)):
        fend = None
    return cit, fdate, fend, "; ".join(notes) or None


def _title_key(title: str | None) -> str:
    return re.sub(r"[^a-zäöüß0-9 ]", "", (title or "").lower())


def _merge_duplicate_facts(conn: sqlite3.Connection, case_id: str) -> int:
    """Chunks overlap or the same event is phrased twice, so a fact can be
    extracted more than once — with different causality labels. Merge entries
    that share document, date and laterality when they are either the same
    event (same category, compatible body region) or near-identical titles.
    The verified, more detailed entry wins."""
    rows = [dict(r) for r in conn.execute(
        "SELECT id, document_id, fact_date, title, laterality, body_region,"
        " event_category, verified, LENGTH(summary) AS n"
        " FROM facts WHERE case_id=? AND reviewed=0 ORDER BY id", (case_id,))]

    def lat_ok(a, b) -> bool:
        return a["laterality"] in (b["laterality"], "na", None) \
            or b["laterality"] in ("na", None)

    def region_ok(a, b) -> bool:
        return a["body_region"] in (b["body_region"], None, "") \
            or b["body_region"] in (None, "")

    def same_event(a, b) -> bool:
        if not lat_ok(a, b):
            return False
        if SequenceMatcher(None, _title_key(a["title"]),
                           _title_key(b["title"])).ratio() >= 0.8:
            return True
        # same category and region alone is not enough for examinations: "Röntgen
        # Knie" and "MRT Knie" of the same day are two findings, and merging would
        # drop one of them (operations are merged: the same operation is often
        # extracted several times under different titles)
        if a["event_category"] == "diagnostik":
            return False
        return (a["event_category"] == b["event_category"]
                and region_ok(a, b))

    def wins(f, twin) -> bool:
        return (f["verified"], f["n"], -f["id"]) > (twin["verified"], twin["n"], -twin["id"])

    groups: dict[tuple, list[dict]] = {}
    for f in rows:
        if f["fact_date"]:
            groups.setdefault((f["document_id"], f["fact_date"]), []).append(f)
    dead: set[int] = set()
    for group in groups.values():
        keep: list[dict] = []
        for f in group:
            twin = next((g for g in keep if same_event(g, f)), None)
            if twin is None:
                keep.append(f)
            elif wins(f, twin):
                dead.add(twin["id"])
                keep.remove(twin)
                keep.append(f)
            else:
                dead.add(f["id"])
    if dead:
        conn.execute(
            f"DELETE FROM facts WHERE id IN ({','.join('?' * len(dead))})", tuple(dead))
    return len(dead)


def run_extract(
    conn: sqlite3.Connection, case_id: str, llm: JsonLLM, progress: Progress | None = None
) -> dict:
    case = conn.execute("SELECT accident_date FROM cases WHERE id=?", (case_id,)).fetchone()
    docs = [dict(r) for r in conn.execute(
        "SELECT * FROM documents WHERE case_id=? AND excluded=0 ORDER BY start_seq",
        (case_id,)
    )]
    conn.execute(
        "DELETE FROM timeline_entries WHERE case_id=? AND created_by='pipeline' AND edited=0",
        (case_id,),
    )
    conn.execute("DELETE FROM facts WHERE case_id=? AND reviewed=0", (case_id,))

    total = verified = failed_calls = corrected = 0
    for i, doc in enumerate(docs, start=1):
        if progress:
            progress("Extraktion", i, len(docs))
        pages = [p for p in _doc_pages(conn, doc) if p["text"].strip()]
        for ci, chunk in enumerate(chunk_pages(pages), start=1):
            prompt = FACT_EXTRACT_PROMPT.format(
                accident_date=case["accident_date"] or "unbekannt",
                doc_title=doc["title"], doc_type=doc["doc_type"],
                doc_date=doc["doc_date"] or "unbekannt",
                doc_text=_render(chunk),
            )
            try:
                out = call_llm(
                    conn, case_id, llm, stage="fact_extract",
                    ref=f"doc {doc['id']} chunk {ci}", prompt_version=FACT_EXTRACT_VERSION,
                    prompt=prompt, schema=FACT_EXTRACTION_SCHEMA, max_tokens=6144,
                )
            except LlmError:
                failed_calls += 1
                continue
            for fact in out.get("facts", []):
                cit, fdate, fend, note = _verify(conn, fact, chunk, doc["doc_date"])
                ok = note is None
                page_id = cit.page_id if cit else next(
                    (p["id"] for p in chunk if p["global_seq"] == fact.get("page")),
                    chunk[0]["id"],
                )
                conn.execute(
                    """INSERT INTO facts
                       (case_id, document_id, page_id, fact_date, fact_date_end,
                        event_category, causality,
                        body_region, laterality, icd10, title, summary, quote, confidence,
                        block_ids, bbox, quote_score, verified, verify_note,
                        prompt_version, model_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        case_id, doc["id"], page_id, fdate, fend,
                        fact.get("event_category") if fact.get("event_category")
                        in CATEGORIES else None,
                        causality_for(fact.get("causality"), fdate, case["accident_date"]),
                        fact.get("body_region"),
                        fact.get("laterality") if fact.get("laterality") in LATERALITY
                        else "na",
                        fact.get("icd10"), fact.get("title") or "", fact.get("summary"),
                        fact.get("quote"), cit.score if cit else None,
                        json.dumps(cit.block_ids if cit else []),
                        json.dumps(cit.bbox) if cit and cit.bbox else None,
                        cit.score if cit else None, int(ok), note,
                        FACT_EXTRACT_VERSION, llm.model_id,
                    ),
                )
                total += 1
                verified += ok
                fixed = causality_for(fact.get("causality"), fdate, case["accident_date"])
                if case["accident_date"] and fact.get("causality") != fixed:
                    corrected += 1
        conn.commit()

    merged = _merge_duplicate_facts(conn, case_id)
    if merged:
        rows = conn.execute(
            "SELECT COUNT(*) AS n, SUM(verified) AS v FROM facts WHERE case_id=?",
            (case_id,)).fetchone()
        total, verified = rows["n"], rows["v"] or 0
    database.audit(
        conn, case_id, "facts_extracted",
        f"{total} Angaben ({verified} belegt, {total - verified} unbelegt),"
        f" {corrected} Kausalitätsangaben nach Datumslogik korrigiert,"
        f" {merged} doppelte Angaben zusammengeführt,"
        f" {failed_calls} fehlgeschlagene LLM-Aufrufe",
    )
    conn.commit()
    return {"facts": total, "verified": verified, "unverified": total - verified,
            "merged": merged, "llm_failures": failed_calls}
