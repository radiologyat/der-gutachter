# SPDX-License-Identifier: AGPL-3.0-or-later
"""Case lifecycle: creation, storage layout, listing, workflow stage."""
from __future__ import annotations

import json
import logging
import re
import secrets
import sqlite3
from pathlib import Path

from . import config
from .db import database

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | PDF_SUFFIXES

log = logging.getLogger(__name__)


class CaseNotFound(KeyError):
    """Unknown case id — the API maps this to 404."""

# Workflow stages, in order. Computed from case state — never stored,
# so it can never lie about where the case actually is.
STAGES = [
    ("intake", "Eingang / Digitalisierung"),
    ("ocr", "Digitalisiert"),
    ("index", "Registriert"),
    ("analysis", "Ausgewertet"),
    ("draft", "Entwurf"),
    ("done", "Fertig"),
]


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:40] or "fall"


def case_db_path(case_id: str) -> Path:
    return config.case_dir(case_id) / "case.db"


def connect_case(case_id: str) -> sqlite3.Connection:
    path = case_db_path(case_id)
    if not path.exists():
        raise CaseNotFound(case_id)
    database.migrate(path)  # idempotent — upgrades older case DBs
    return database.connect(path)


def create_case(
    title: str,
    patient_ref: str = "",
    patient_dob: str | None = None,
    jurisdiction: str = "CH",
    case_type: str = "unfall",
    accident_date: str | None = None,
    auftraggeber: str = "",
) -> str:
    config.ensure_dirs()
    case_id = f"{_slugify(title)}-{secrets.token_hex(3)}"
    cdir = config.case_dir(case_id)
    for sub in ("inbox", "pages", "exports"):
        (cdir / sub).mkdir(parents=True, exist_ok=True)
    db_path = cdir / "case.db"
    database.migrate(db_path)
    conn = database.connect(db_path)
    conn.execute(
        """INSERT INTO cases
           (id, title, patient_ref, patient_dob, jurisdiction, case_type,
            accident_date, auftraggeber)
           VALUES (?,?,?,?,?,?,?,?)""",
        (case_id, title, patient_ref, patient_dob, jurisdiction, case_type,
         accident_date, auftraggeber),
    )
    database.audit(conn, case_id, "case_created", title)
    conn.commit()
    conn.close()
    return case_id


def update_case(case_id: str, fields: dict) -> None:
    allowed = {
        "title", "patient_ref", "patient_dob", "jurisdiction",
        "case_type", "accident_date", "auftraggeber", "notes",
        # formal details for the report (KSVI Anhang IV 1.1/1.2)
        "patient_name", "patient_address", "ahv_nr", "identity_check", "order_date",
        "received_date", "exam_date", "exam_start", "exam_end", "interpreter",
        "completed_date", "job_profile",
    }
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    conn = connect_case(case_id)
    sql = ", ".join(f"{k}=?" for k in sets)
    conn.execute(
        f"UPDATE cases SET {sql}, updated_at=datetime('now') WHERE id=?",
        (*sets.values(), case_id),
    )
    database.audit(conn, case_id, "case_updated", str(sets), actor="user")
    conn.commit()
    conn.close()


def compute_stage(conn: sqlite3.Connection, case_id: str) -> str:
    """Derive the workflow stage from actual case state."""
    pages = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(status='pending'),0) p FROM pages WHERE case_id=?",
        (case_id,),
    ).fetchone()
    if pages["c"] == 0 or pages["p"] > 0:
        return "intake"  # no pages yet, or OCR still pending on some
    docs = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE case_id=?", (case_id,)
    ).fetchone()["c"]
    if docs == 0:
        return "ocr"  # digitized, not yet indexed into documents
    facts = conn.execute(
        "SELECT COUNT(*) c FROM facts WHERE case_id=?", (case_id,)
    ).fetchone()["c"]
    if facts == 0:
        return "index"
    drafts = conn.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(status='approved'),0) a"
        " FROM draft_sections WHERE case_id=?",
        (case_id,),
    ).fetchone()
    if drafts["c"] == 0:
        return "analysis"
    return "done" if drafts["c"] == drafts["a"] else "draft"


def _case_stats(conn: sqlite3.Connection, case_id: str) -> dict:
    pages = conn.execute(
        "SELECT COUNT(*) pages,"
        " COALESCE(SUM(status='pending'),0) pending,"
        " COALESCE(SUM(status='ocr_done'),0) ocr_done,"
        " COALESCE(SUM(status='review'),0) review,"
        " COALESCE(SUM(status='manual'),0) manual"
        " FROM pages WHERE case_id=?",
        (case_id,),
    ).fetchone()
    docs = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE case_id=?", (case_id,)
    ).fetchone()["c"]
    return {**dict(pages), "documents": docs}


def _next_date(conn: sqlite3.Connection, case_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, kind, date, label FROM case_dates"
        " WHERE case_id=? AND done=0 ORDER BY date LIMIT 1",
        (case_id,),
    ).fetchone()
    return dict(row) if row else None


def _enrich(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = dict(row)
    d["stats"] = _case_stats(conn, row["id"])
    d["stage"] = compute_stage(conn, row["id"])
    d["next_date"] = _next_date(conn, row["id"])
    d["pipeline"] = json.loads(d.get("pipeline_json") or "{}")
    return d


def set_pipeline(case_id: str, **fields) -> None:
    """Persist how far the one-click evaluation got (survives closing the app)."""
    conn = connect_case(case_id)
    try:
        cur = json.loads(conn.execute("SELECT pipeline_json FROM cases WHERE id=?",
                                      (case_id,)).fetchone()[0] or "{}")
        cur.update(fields)
        conn.execute("UPDATE cases SET pipeline_json=? WHERE id=?",
                     (json.dumps(cur, ensure_ascii=False), case_id))
        conn.commit()
    finally:
        conn.close()


def list_cases() -> list[dict]:
    config.ensure_dirs()
    out = []
    for cdir in sorted(config.CASES_DIR.iterdir()):
        db = cdir / "case.db"
        if not db.exists():
            continue
        try:
            database.migrate(db)  # older case DBs lack e.g. case_dates
            conn = database.connect(db)
            try:
                row = conn.execute("SELECT * FROM cases").fetchone()
                if row:
                    out.append(_enrich(conn, row))
            finally:
                conn.close()
        except Exception:
            # One damaged case must not take the whole Arbeitsliste down.
            log.exception("skipping unreadable case %s", cdir.name)
    return out


def get_case(case_id: str) -> dict:
    conn = connect_case(case_id)
    row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        conn.close()
        raise CaseNotFound(case_id)
    d = _enrich(conn, row)
    conn.close()
    return d


# ------------------------------------------------------------------ dates

def list_dates(conn: sqlite3.Connection, case_id: str) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM case_dates WHERE case_id=? ORDER BY done, date", (case_id,)
        )
    ]


def add_date(case_id: str, kind: str, date: str, label: str = "") -> int:
    conn = connect_case(case_id)
    cur = conn.execute(
        "INSERT INTO case_dates (case_id, kind, date, label) VALUES (?,?,?,?)",
        (case_id, kind, date, label),
    )
    database.audit(conn, case_id, "date_added", f"{kind} {date} {label}", actor="user")
    conn.commit()
    conn.close()
    return cur.lastrowid


def update_date(case_id: str, date_id: int, done: bool) -> None:
    conn = connect_case(case_id)
    conn.execute("UPDATE case_dates SET done=? WHERE id=? AND case_id=?",
                 (int(done), date_id, case_id))
    database.audit(conn, case_id, "date_done" if done else "date_reopened",
                   f"id={date_id}", actor="user")
    conn.commit()
    conn.close()


def delete_date(case_id: str, date_id: int) -> None:
    conn = connect_case(case_id)
    row = conn.execute(
        "SELECT kind, date, label FROM case_dates WHERE id=? AND case_id=?",
        (date_id, case_id),
    ).fetchone()
    conn.execute("DELETE FROM case_dates WHERE id=? AND case_id=?", (date_id, case_id))
    if row:
        database.audit(conn, case_id, "date_deleted",
                       f"{row['kind']} {row['date']} {row['label'] or ''}".strip(),
                       actor="user")
    conn.commit()
    conn.close()
