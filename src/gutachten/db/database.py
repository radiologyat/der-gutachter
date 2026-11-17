# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite access: connections, migrations, audit helper."""
from __future__ import annotations

import sqlite3
from pathlib import Path

# Ordered migrations: (version, sql file next to this module).
MIGRATIONS = [
    (1, "schema.sql"),
    (2, "schema_v2.sql"),
    (3, "schema_v3.sql"),
    (4, "schema_v4.sql"),
    (5, "schema_v5.sql"),
    (6, "schema_v6.sql"),
    (7, "schema_v7.sql"),
    (8, "schema_v8.sql"),
    (9, "schema_v9.sql"),
    (10, "schema_v10.sql"),
    (11, "schema_v11.sql"),
    (12, "schema_v12.sql"),
    (13, "schema_v13.sql"),
    (14, "schema_v14.sql"),
]
_SCHEMA_DIR = Path(__file__).parent


def connect(db_path: Path) -> sqlite3.Connection:
    # timeout: wait for a concurrent writer (ingest vs. OCR) instead of failing
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations"
            " (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        current = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
        if current and any(v > current for v, _ in MIGRATIONS):
            _backup(conn, db_path, current)
        for version, fname in MIGRATIONS:
            if version <= current:
                continue
            sql = (_SCHEMA_DIR / fname).read_text(encoding="utf-8")
            # One transaction per migration: DDL and the version row commit together,
            # so a crash can't leave e.g. an applied ALTER TABLE without its version.
            try:
                conn.executescript(
                    f"BEGIN;\n{sql}\n"
                    f"INSERT INTO schema_migrations (version) VALUES ({int(version)});\n"
                    "COMMIT;"
                )
            except Exception:
                conn.rollback()
                raise
    finally:
        conn.close()


KEEP_BACKUPS = 3


def _backup(conn: sqlite3.Connection, db_path: Path, version: int) -> None:
    """Before a newer app version updates a case database: a consistent copy of the
    old state (sqlite backup API, safe with WAL) in backups/ next to it. The last
    three are kept. A failed backup (e.g. disk full) stops the update — the case
    stays unchanged and readable."""
    folder = db_path.parent / "backups"
    folder.mkdir(exist_ok=True)
    dest = folder / f"{db_path.stem}-v{version}.db"
    if not dest.exists():
        out = sqlite3.connect(dest)
        try:
            conn.backup(out)
        finally:
            out.close()
    old = sorted(folder.glob(f"{db_path.stem}-v*.db"), key=lambda f: f.stat().st_mtime)
    for f in old[:-KEEP_BACKUPS]:
        f.unlink(missing_ok=True)


def audit(
    conn: sqlite3.Connection,
    case_id: str,
    action: str,
    detail: str = "",
    actor: str = "system",
) -> None:
    conn.execute(
        "INSERT INTO audit_log (case_id, actor, action, detail) VALUES (?,?,?,?)",
        (case_id, actor, action, detail),
    )
