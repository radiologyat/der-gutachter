# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page-level duplicate detection.

Akten regularly contain the same page twice (copy in the insurer's file,
re-sent reports). File-level SHA-256 only catches identical files; here pages
are compared by their recognized text, which also matches a scanned copy
against the born-digital original (their images and hashes differ).

Duplicates keep their Bl.-number — citations must stay stable — but are
marked `duplicate_of` the first occurrence and skipped for extraction.
"""
from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher

from ..citations import normalize
from ..db import database

MIN_CHARS = 200          # short pages (forms, cover sheets) are too generic to call
MIN_SIMILARITY = 0.92


def find_duplicate_pages(conn: sqlite3.Connection, case_id: str) -> list[tuple[int, int, float]]:
    """Mark later copies of a page; returns [(global_seq, duplicate_of_seq, score)]."""
    pages = [
        {**dict(r), "norm": normalize(r["text"] or "")}
        for r in conn.execute(
            """SELECT p.id, p.global_seq, pt.text_md AS text
               FROM pages p LEFT JOIN page_text pt ON pt.page_id=p.id
               WHERE p.case_id=? ORDER BY p.global_seq""",
            (case_id,),
        )
    ]
    conn.execute(
        "UPDATE pages SET duplicate_of=NULL, duplicate_score=NULL WHERE case_id=?", (case_id,)
    )
    originals: list[dict] = []
    found: list[tuple[int, int, float]] = []
    sm = SequenceMatcher(autojunk=False)
    for p in pages:
        t = p["norm"]
        if len(t) < MIN_CHARS:
            continue
        sm.set_seq2(t)
        best = None
        for o in originals:
            if not 0.85 < len(o["norm"]) / len(t) < 1.18:
                continue
            sm.set_seq1(o["norm"])
            if sm.real_quick_ratio() < MIN_SIMILARITY or sm.quick_ratio() < MIN_SIMILARITY:
                continue
            r = sm.ratio()
            if r >= MIN_SIMILARITY and (best is None or r > best[1]):
                best = (o, r)
        if best:
            o, r = best
            conn.execute(
                "UPDATE pages SET duplicate_of=?, duplicate_score=? WHERE id=?",
                (o["id"], round(r, 3), p["id"]),
            )
            found.append((p["global_seq"], o["global_seq"], round(r, 3)))
        else:
            originals.append(p)
    if found:
        database.audit(
            conn, case_id, "duplicate_pages",
            ", ".join(f"Bl. {s} = Bl. {o} ({r:.0%})" for s, o, r in found),
        )
    conn.commit()
    return found
