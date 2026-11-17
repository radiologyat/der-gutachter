# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chronologie-Builder: verified facts -> Aktenauszug (timeline_entries).

Facts describing the same event (same date, category, laterality and a
similar title, or the same ICD-10 code) are merged into one entry carrying all
citations — e.g. the OP reported in the OP-Bericht and again in two Arztbriefe.

Rebuilds replace only pipeline rows the user has not edited.
"""
from __future__ import annotations

import json
import re
import sqlite3
from difflib import SequenceMatcher

from ..citations import normalize
from ..db import database

TITLE_SIMILARITY = 0.75
MIN_SUBSET_WORDS = 3


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", normalize(text)))


def _same_event(entry: dict, fact: dict) -> bool:
    if entry["entry_date"] != fact["fact_date"]:
        return False
    if entry["category"] != fact["event_category"]:
        return False
    if (entry["laterality"] or "na") != (fact["laterality"] or "na"):
        return False
    # One document rarely reports two separate events of the same kind on one
    # day: MRI "Befund" + "Beurteilung", OP "Eingriff" + "intraoperativer Befund".
    if fact["document_id"] in entry["doc_ids"]:
        return True
    if fact["icd10"] and fact["icd10"] in entry["icd10s"]:
        return True
    a, b = normalize(entry["title"]), normalize(fact["title"] or "")
    if SequenceMatcher(None, a, b).ratio() >= TITLE_SIMILARITY:
        return True
    # different word order / extra words: "Teilmeniskektomie medial links" is the
    # same event as "Arthroskopie Knie links, Teilmeniskektomie medial"
    wa, wb = _words(a), _words(b)
    small, big = sorted((wa, wb), key=len)
    return len(small) >= MIN_SUBSET_WORDS and small <= big


def _citation(fact: dict) -> dict:
    return {
        "fact_id": fact["id"],
        "page_id": fact["page_id"],
        "global_seq": fact["global_seq"],
        "block_ids": json.loads(fact["block_ids"] or "[]"),
        "bbox": json.loads(fact["bbox"]) if fact["bbox"] else None,
        "quote": fact["quote"],
        "document_id": fact["document_id"],
        "doc_title": fact["doc_title"],
    }


def build_timeline(conn: sqlite3.Connection, case_id: str) -> dict:
    facts = [dict(r) for r in conn.execute(
        """SELECT f.*, p.global_seq, d.title AS doc_title
           FROM facts f
           JOIN pages p ON p.id = f.page_id
           LEFT JOIN documents d ON d.id = f.document_id
           WHERE f.case_id=? AND f.verified=1 AND f.fact_date IS NOT NULL
             AND COALESCE(d.excluded, 0) = 0
           ORDER BY f.fact_date, p.global_seq, f.id""",
        (case_id,),
    )]
    entries: list[dict] = []
    for f in facts:
        match = next((e for e in reversed(entries) if _same_event(e, f)), None)
        if match:
            if f["document_id"] in match["doc_ids"]:
                # same document: keep the extra detail instead of a second row
                extra = (f["title"] or "").strip()
                if extra and normalize(extra) not in normalize(match["summary"] or ""):
                    match["summary"] = "; ".join(x for x in (match["summary"], extra) if x)
            match["doc_ids"].add(f["document_id"])
            match["citations"].append(_citation(f))
            if f["icd10"]:
                match["icd10s"].add(f["icd10"])
            if f["fact_date_end"] and not match["date_end"]:
                match["date_end"] = f["fact_date_end"]
            if f["causality"] != match["causality"]:
                match["causality"] = "unklar"  # sources disagree -> physician decides
            continue
        entries.append({
            "entry_date": f["fact_date"],
            "date_end": f["fact_date_end"],
            "category": f["event_category"],
            "causality": f["causality"],
            "laterality": f["laterality"],
            "body_region": f["body_region"],
            "title": f["title"],
            "summary": f["summary"],
            "icd10s": {f["icd10"]} if f["icd10"] else set(),
            "doc_ids": {f["document_id"]},
            "citations": [_citation(f)],
        })

    conn.execute(
        "DELETE FROM timeline_entries WHERE case_id=? AND created_by='pipeline' AND edited=0",
        (case_id,),
    )
    # rows the expert edited, excluded or added survive; the pipeline must not add the
    # same event a second time next to them
    kept_facts = {c.get("fact_id") for r in conn.execute(
        "SELECT citations FROM timeline_entries WHERE case_id=?", (case_id,))
        for c in json.loads(r[0] or "[]") if c.get("fact_id")}
    entries = [e for e in entries
               if not any(c.get("fact_id") in kept_facts for c in e["citations"])]
    for i, e in enumerate(entries):
        conn.execute(
            """INSERT INTO timeline_entries
               (case_id, entry_date, date_end, category, causality, laterality,
                body_region, title, summary, citations, sort, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, 'pipeline')""",
            (case_id, e["entry_date"], e["date_end"], e["category"], e["causality"],
             e["laterality"], e["body_region"], e["title"], e["summary"],
             json.dumps(e["citations"], ensure_ascii=False), i),
        )
    database.audit(
        conn, case_id, "timeline_built",
        f"{len(entries)} Einträge aus {len(facts)} belegten Angaben",
    )
    conn.commit()
    return {"entries": len(entries), "facts_used": len(facts)}


# ------------------------------------------------------------------ manual corrections

EDITABLE = ("entry_date", "date_end", "category", "causality", "laterality", "body_region",
            "title", "summary")


def _row(conn, case_id: str, eid: int) -> dict:
    r = conn.execute("SELECT * FROM timeline_entries WHERE case_id=? AND id=?",
                     (case_id, eid)).fetchone()
    if not r:
        raise KeyError(eid)
    return dict(r)


def add_entry(conn, case_id: str, data: dict, seq: int | None = None) -> int:
    """Manual entry. With a page number it cites that page (Bl.), else it is marked
    "ohne Beleg (manuell)" in the Aktenauszug."""
    cites = []
    if seq:
        page = conn.execute("SELECT id FROM pages WHERE case_id=? AND global_seq=?",
                            (case_id, seq)).fetchone()
        if not page:
            raise ValueError(f"Bl. {seq} existiert nicht")
        cites = [{"page_id": page[0], "global_seq": seq, "block_ids": [], "bbox": None,
                  "quote": data.get("quote") or ""}]
    cur = conn.execute(
        f"""INSERT INTO timeline_entries (case_id, {", ".join(EDITABLE)}, citations, sort,
            created_by, reviewed, updated_at)
            VALUES (?, {", ".join("?" * len(EDITABLE))}, ?, 999, 'user', 1, datetime('now'))""",
        (case_id, *(data.get(k) for k in EDITABLE), json.dumps(cites, ensure_ascii=False)))
    database.audit(conn, case_id, "auszug_manual_added",
                   f"{data.get('entry_date')} {data.get('title')}"
                   + (f" (Bl. {seq})" if seq else " (ohne Beleg)"), actor="user")
    conn.commit()
    return cur.lastrowid


def update_entry(conn, case_id: str, eid: int, data: dict) -> dict:
    row = _row(conn, case_id, eid)
    changes = {k: data[k] for k in EDITABLE if k in data and data[k] != row[k]}
    if not changes:
        return row
    original = row["original_json"]
    if row["created_by"] == "pipeline" and not original:
        original = json.dumps({k: row[k] for k in EDITABLE}, ensure_ascii=False)
    conn.execute(
        f"""UPDATE timeline_entries SET {", ".join(f"{k}=?" for k in changes)}, edited=1,
            original_json=?, reviewed=1, updated_at=datetime('now') WHERE id=?""",
        (*changes.values(), original, eid))
    database.audit(conn, case_id, "auszug_edited",
                   f"#{eid}: " + "; ".join(f"{k}: {row[k]!s:.40} → {v!s:.40}"
                                         for k, v in changes.items()), actor="user")
    conn.commit()
    return _row(conn, case_id, eid)


def restore_entry(conn, case_id: str, eid: int) -> dict:
    """Back to the pipeline's version; the next rebuild may replace it again."""
    row = _row(conn, case_id, eid)
    if not row["original_json"]:
        raise ValueError("kein Original gespeichert")
    orig = json.loads(row["original_json"])
    conn.execute(
        f"""UPDATE timeline_entries SET {", ".join(f"{k}=?" for k in EDITABLE)}, edited=0,
            original_json=NULL, excluded=0, updated_at=datetime('now') WHERE id=?""",
        (*(orig.get(k) for k in EDITABLE), eid))
    database.audit(conn, case_id, "auszug_restored", f"#{eid}", actor="user")
    conn.commit()
    return _row(conn, case_id, eid)


def set_flag(conn, case_id: str, eid: int, flag: str, value: bool) -> dict:
    """excluded (kept for the record, not used downstream) or reviewed."""
    if flag not in ("excluded", "reviewed"):
        raise ValueError(flag)
    row = _row(conn, case_id, eid)
    # excluding freezes the row: a rebuild must not bring the event back
    extra = ", edited=1" if flag == "excluded" and value and row["created_by"] == "pipeline" \
        else ""
    if extra and not row["original_json"]:
        extra += ", original_json=?"
        args = (int(value), json.dumps({k: row[k] for k in EDITABLE}, ensure_ascii=False), eid)
    else:
        args = (int(value), eid)
    conn.execute(f"UPDATE timeline_entries SET {flag}=?{extra}, updated_at=datetime('now') "
                 "WHERE id=?", args)
    database.audit(conn, case_id, f"auszug_{flag}", f"#{eid}: {value} ({row['title'][:60]})",
                   actor="user")
    conn.commit()
    return _row(conn, case_id, eid)


def review_all(conn, case_id: str) -> int:
    n = conn.execute("UPDATE timeline_entries SET reviewed=1 WHERE case_id=? AND reviewed=0 "
                     "AND excluded=0", (case_id,)).rowcount
    database.audit(conn, case_id, "auszug_reviewed_all", str(n), actor="user")
    conn.commit()
    return n


def delete_manual(conn, case_id: str, eid: int) -> None:
    row = _row(conn, case_id, eid)
    if row["created_by"] == "pipeline":
        raise ValueError("Einträge aus der Akte werden ausgeschlossen, nicht gelöscht")
    conn.execute("DELETE FROM timeline_entries WHERE id=?", (eid,))
    database.audit(conn, case_id, "auszug_manual_deleted", f"#{eid}: {row['title'][:60]}",
                   actor="user")
    conn.commit()
