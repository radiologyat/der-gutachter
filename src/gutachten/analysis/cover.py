# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deckblatt-Parsing: read the first pages (Gutachtenauftrag / Beweisbeschluss)
and turn case metadata, deadlines and Beweisfragen into *suggestions*.

Nothing is applied automatically: the user accepts or rejects each one. A
suggestion is `verified` when its quote (for questions: the question itself)
is found on the cover pages and its date is written there.
"""
from __future__ import annotations

import json
import re
import sqlite3

from ..cases import connect_case
from ..citations import locate_quote
from ..dates import date_supported, normalize_iso
from ..db import database
from ..llm.client import JsonLLM
from ..llm.prompts import COVER_PROMPT, COVER_V1
from ..llm.schemas import COVER_SCHEMA
from .common import call_llm, page_texts

COVER_PAGES = 3
DATE_FIELDS = {"patient_dob", "accident_date"}


ENUM = re.compile(r"^\s*(?:\d{1,2}|[a-z])[.)]\s+")


def _cite(conn, page_ids, quote):
    c = locate_quote(conn, page_ids, quote or "")
    return c.to_json(quote) if c else None


# words of an assignment / order letter (Gutachtenauftrag, Beweisbeschluss)
ASSIGNMENT = re.compile(
    r"gutachtenauftrag|begutachtungsauftrag|auftrag zur begutachtung|gutachten in auftrag|"
    r"fragestellung|beweisfragen|fragenkatalog|beweisbeschluss|ersuchen sie|bitten sie,? "
    r"(?:ein|die versicherte)|medizinische abklärung|polydisziplinär|mono?disziplinär",
    re.I)
SEARCH_PAGES = 40


def assignment_score(text: str) -> int:
    return len(ASSIGNMENT.findall(text or ""))


def assignment_pages(conn: sqlite3.Connection, case_id: str) -> list[int]:
    """Where the assignment is: the page (among the first 40) with most assignment
    words, plus the following pages of the same file (up to 3). Falls back to the
    first pages. A choice made by the expert (pipeline_json.cover_pages) wins."""
    row = conn.execute("SELECT pipeline_json FROM cases WHERE id=?", (case_id,)).fetchone()
    chosen = json.loads(row[0] or "{}").get("cover_pages") if row else None
    pages = page_texts(conn, case_id)
    if chosen:
        a, b = chosen
        return [p["global_seq"] for p in pages if a <= p["global_seq"] <= b]
    scored = [(assignment_score(p["text"]), -p["global_seq"], p) for p in pages[:SEARCH_PAGES]]
    best = max(scored, default=None, key=lambda x: (x[0], x[1]))
    if not best or best[0] == 0:
        return [p["global_seq"] for p in pages[:COVER_PAGES]]
    start = best[2]
    same = [p for p in pages if p["source_id"] == start["source_id"]
            and p["global_seq"] >= start["global_seq"]]
    return [p["global_seq"] for p in same[:COVER_PAGES]]


def run_cover(conn: sqlite3.Connection, case_id: str, llm: JsonLLM) -> dict:
    want = set(assignment_pages(conn, case_id))
    pages = [p for p in page_texts(conn, case_id)
             if p["global_seq"] in want and p["text"].strip()]
    if not pages:
        return {"suggestions": 0}
    ids = [p["id"] for p in pages]
    text = "\n\n".join(f"=== Bl. {p['global_seq']} d. A. ===\n{p['text']}" for p in pages)
    out = call_llm(
        conn, case_id, llm, stage="cover",
        ref=f"Bl. {pages[0]['global_seq']}–{pages[-1]['global_seq']}",
        prompt_version=COVER_V1, prompt=COVER_PROMPT.format(text=text),
        schema=COVER_SCHEMA, max_tokens=4096,
    )
    conn.execute("DELETE FROM suggestions WHERE case_id=? AND status='open'", (case_id,))
    rows: list[tuple[str, dict, dict | None, bool]] = []

    for name in ("auftraggeber", "aktenzeichen", "patient_name", "patient_dob",
                 "accident_date"):
        item = out.get(name)
        if not item or not (item.get("value") or "").strip():
            continue
        value = item["value"].strip()
        cit = _cite(conn, ids, item.get("quote"))
        ok = cit is not None
        if name in DATE_FIELDS:
            value = normalize_iso(value) or ""
            ok = ok and bool(value) and date_supported(value, cit["quote"] if cit else "")
            if not value:
                continue
        rows.append(("case_field", {"field": name, "value": value}, cit, ok))

    for d in out.get("deadlines", []):
        iso = normalize_iso(d.get("date"))
        if not iso:
            continue
        cit = _cite(conn, ids, d.get("quote"))
        ok = cit is not None and date_supported(iso, d.get("quote") or "")
        rows.append(("date", {"kind": d.get("kind", "frist"), "date": iso,
                              "label": d.get("label", "")}, cit, ok))

    for q in out.get("questions", []):
        q = (q or "").strip()
        if not q:
            continue
        cit = _cite(conn, ids, q)  # Beweisfragen must be verbatim
        # the report numbers questions itself: drop "1." / "a)" taken over from the letter
        rows.append(("question", {"text": ENUM.sub("", q)}, cit, cit is not None))

    for kind, payload, cit, ok in rows:
        conn.execute(
            "INSERT INTO suggestions (case_id, kind, payload, citation, verified)"
            " VALUES (?,?,?,?,?)",
            (case_id, kind, json.dumps(payload, ensure_ascii=False),
             json.dumps(cit, ensure_ascii=False) if cit else None, int(ok)),
        )
    database.audit(conn, case_id, "cover_parsed", f"{len(rows)} Vorschläge")
    conn.commit()
    return {"suggestions": len(rows), "verified": sum(r[3] for r in rows),
            "pages": [pages[0]["global_seq"], pages[-1]["global_seq"]]}


def list_suggestions(case_id: str) -> list[dict]:
    conn = connect_case(case_id)
    try:
        out = []
        for r in conn.execute(
            "SELECT * FROM suggestions WHERE case_id=? ORDER BY status='open' DESC, id",
            (case_id,),
        ):
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            d["citation"] = json.loads(d["citation"]) if d["citation"] else None
            out.append(d)
        return out
    finally:
        conn.close()


_FIELD_TARGET = {
    "auftraggeber": "auftraggeber",
    "patient_dob": "patient_dob",
    "accident_date": "accident_date",
    "patient_name": "patient_name",   # full name for the report (patient_ref = pseudonym)
}


def _apply(conn, case_id: str, kind: str, p: dict) -> dict:
    """Apply one suggestion; returns what was changed so it can be undone exactly."""
    if kind == "case_field":
        if p["field"] == "aktenzeichen":
            old = conn.execute("SELECT notes FROM cases WHERE id=?", (case_id,)).fetchone()[0]
            conn.execute(
                "UPDATE cases SET notes = TRIM(COALESCE(notes,'') || char(10) ||"
                " 'Aktenzeichen: ' || ?), updated_at=datetime('now') WHERE id=?",
                (p["value"], case_id))
            return {"column": "notes", "previous": old}
        col = _FIELD_TARGET[p["field"]]  # whitelisted column name
        old = conn.execute(f"SELECT {col} FROM cases WHERE id=?", (case_id,)).fetchone()[0]
        conn.execute(f"UPDATE cases SET {col}=?, updated_at=datetime('now') WHERE id=?",
                     (p["value"], case_id))
        return {"column": col, "previous": old}
    if kind == "date":
        cur = conn.execute(
            "INSERT INTO case_dates (case_id, kind, date, label) VALUES (?,?,?,?)",
            (case_id, p["kind"], p["date"], p["label"]))
        return {"case_date_id": cur.lastrowid}
    if kind == "question":
        n = conn.execute("SELECT COALESCE(MAX(ord),0) FROM questions WHERE case_id=?",
                         (case_id,)).fetchone()[0]
        cur = conn.execute("INSERT INTO questions (case_id, ord, text) VALUES (?,?,?)",
                           (case_id, n + 1, p["text"]))
        return {"question_id": cur.lastrowid}
    return {}


def decide_suggestion(case_id: str, sid: int, accept: bool, auto: bool = False) -> dict:
    conn = connect_case(case_id)
    try:
        row = conn.execute(
            "SELECT * FROM suggestions WHERE id=? AND case_id=?", (sid, case_id)
        ).fetchone()
        if not row:
            raise KeyError(sid)
        if row["status"] != "open":
            return {"status": row["status"]}
        applied = _apply(conn, case_id, row["kind"], json.loads(row["payload"])) \
            if accept else None
        status = "accepted" if accept else "rejected"
        conn.execute("UPDATE suggestions SET status=?, auto=?, applied_json=? WHERE id=?",
                     (status, int(auto), json.dumps(applied) if applied else None, sid))
        database.audit(conn, case_id, f"suggestion_{status}" + ("_auto" if auto else ""),
                       f"{row['kind']}: {row['payload']}", actor="system" if auto else "user")
        conn.commit()
        return {"status": status}
    finally:
        conn.close()


def accept_verified(case_id: str, auto: bool = False) -> int:
    """Apply every open suggestion whose quote was found in the Akte."""
    n = 0
    for s in list_suggestions(case_id):
        if s["status"] == "open" and s["verified"]:
            decide_suggestion(case_id, s["id"], True, auto=auto)
            n += 1
    return n


def undo_suggestion(case_id: str, sid: int) -> dict:
    """Revert an applied suggestion exactly and reopen it for review."""
    conn = connect_case(case_id)
    try:
        row = conn.execute("SELECT * FROM suggestions WHERE id=? AND case_id=?",
                           (sid, case_id)).fetchone()
        if not row:
            raise KeyError(sid)
        if row["status"] == "accepted" and row["applied_json"]:
            a = json.loads(row["applied_json"])
            if "column" in a and a["column"] in set(_FIELD_TARGET.values()) | {"notes"}:
                conn.execute(f"UPDATE cases SET {a['column']}=? WHERE id=?",
                             (a["previous"], case_id))
            if "case_date_id" in a:
                conn.execute("DELETE FROM case_dates WHERE id=? AND case_id=?",
                             (a["case_date_id"], case_id))
            if "question_id" in a:
                conn.execute("DELETE FROM questions WHERE id=? AND case_id=?",
                             (a["question_id"], case_id))
        conn.execute("UPDATE suggestions SET status='open', auto=0, applied_json=NULL "
                     "WHERE id=?", (sid,))
        database.audit(conn, case_id, "suggestion_undone", row["payload"], actor="user")
        conn.commit()
        return {"status": "open"}
    finally:
        conn.close()


# ------------------------------------------------------------------ assignment type

_IV = re.compile(r"\bIV[- ]?Stelle|Invalidenversicherung|\bIVST\b|Office AI|Ufficio AI", re.I)
_COURT = re.compile(r"(?<!Versicherungs)(?<!Sozialversicherungs)gericht\b|Gerichtshof|"
                    r"Haftpflicht|Rechtsanwalt|Anwaltskanzlei|Advokatur", re.I)
_UV = re.compile(r"Unfallversicherung|\bSUVA\b|\bUVG\b|Versicherungsgericht", re.I)


def infer_case_type(auftraggeber: str | None) -> str | None:
    """Assignment type from the client: IV office -> IV report (KSVI), accident
    insurer -> UVG report, court / liability insurer / lawyer -> Haftpflicht/Gericht.
    None if the client says nothing clear (the expert chooses)."""
    a = auftraggeber or ""
    if _IV.search(a):
        return "invaliditaet"
    if _UV.search(a):
        return "unfall"
    if _COURT.search(a):
        return "haftpflicht"
    return None


def apply_case_type(case_id: str) -> str | None:
    """After the cover: set the assignment type unless the expert already chose one."""
    conn = connect_case(case_id)
    try:
        row = conn.execute("SELECT auftraggeber, case_type, pipeline_json FROM cases "
                           "WHERE id=?", (case_id,)).fetchone()
        if json.loads(row["pipeline_json"] or "{}").get("case_type_by_user"):
            return None
        t = infer_case_type(row["auftraggeber"])
        if t and t != row["case_type"]:
            conn.execute("UPDATE cases SET case_type=? WHERE id=?", (t, case_id))
            database.audit(conn, case_id, "case_type_inferred",
                           f"{t} (aus Auftraggeber „{row['auftraggeber']}“)")
            conn.commit()
            return t
        return None
    finally:
        conn.close()
