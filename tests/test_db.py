# SPDX-License-Identifier: AGPL-3.0-or-later
import sqlite3

import pytest

from gutachten.cases import case_db_path, connect_case, create_case, get_case
from gutachten.db import database


def test_migrate_idempotent(tmp_path):
    db = tmp_path / "c.db"
    database.migrate(db)
    database.migrate(db)  # second run must not fail
    conn = database.connect(db)
    v = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    conn.close()
    assert v >= 1


def test_case_created_with_metadata():
    cid = create_case(
        title="Muster", patient_ref="MM", jurisdiction="AT",
        case_type="unfall", accident_date="2023-10-09",
        auftraggeber="Fiktive Versicherung",
    )
    case = get_case(cid)
    assert case["jurisdiction"] == "AT"
    assert case["accident_date"] == "2023-10-09"
    conn = connect_case(cid)
    log = conn.execute(
        "SELECT action FROM audit_log WHERE case_id=?", (cid,)
    ).fetchall()
    conn.close()
    assert any(r["action"] == "case_created" for r in log)


def test_schema_has_traceability_columns():
    cid = create_case(title="Schema", jurisdiction="CH", case_type="unfall")
    conn = connect_case(cid)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
    conn.close()
    assert {"quote", "causality", "event_category", "reviewed"} <= cols
    assert (case_db_path(cid)).exists()


def _make_v1_case(case_id: str):
    """Simulate a case created before migration v2 existed."""
    from gutachten import config

    cdir = config.case_dir(case_id)
    cdir.mkdir(parents=True)
    conn = database.connect(cdir / "case.db")
    conn.executescript(
        (database._SCHEMA_DIR / "schema.sql").read_text(encoding="utf-8")
    )
    conn.execute("INSERT INTO schema_migrations (version) VALUES (1)")
    conn.execute("INSERT INTO cases (id, title) VALUES (?, 'Altfall')", (case_id,))
    conn.commit()
    conn.close()


def test_list_cases_upgrades_old_case_dbs():
    """Regression: Arbeitsliste crashed on v1 DBs (no case_dates table)."""
    from gutachten.cases import list_cases

    _make_v1_case("altfall-v1")
    listed = {c["id"]: c for c in list_cases()}
    assert "altfall-v1" in listed
    assert listed["altfall-v1"]["next_date"] is None
    assert listed["altfall-v1"]["stage"] == "intake"


def test_list_cases_skips_a_corrupt_case():
    from gutachten import config
    from gutachten.cases import list_cases

    ok = create_case(title="Heil")
    bad = config.case_dir("kaputt-000000")
    bad.mkdir(parents=True)
    (bad / "case.db").write_bytes(b"this is not sqlite")
    ids = {c["id"] for c in list_cases()}
    assert ok in ids and "kaputt-000000" not in ids


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    (tmp_path / "bad.sql").write_text(
        "CREATE TABLE half_done (x INTEGER);\nTHIS IS NOT SQL;", encoding="utf-8"
    )
    monkeypatch.setattr(database, "_SCHEMA_DIR", tmp_path)
    (tmp_path / "schema.sql").write_text("CREATE TABLE t1 (x INTEGER);", encoding="utf-8")
    monkeypatch.setattr(database, "MIGRATIONS", [(1, "schema.sql"), (2, "bad.sql")])
    with pytest.raises(sqlite3.OperationalError):
        database.migrate(db)
    conn = database.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    conn.close()
    assert "t1" in tables and "half_done" not in tables
    assert version == 1


def test_update_backs_up_the_case_database_first(tmp_path):
    """A newer version updates the case database — the previous state is kept as a
    copy, and the data survive the update."""
    import sqlite3

    from gutachten.db import database

    db = tmp_path / "case.db"
    old = database.MIGRATIONS
    try:
        database.MIGRATIONS = old[:5]                      # an older app version
        database.migrate(db)
        c = database.connect(db)
        c.execute("INSERT INTO cases (id, title) VALUES ('x', 'Fiktiver Fall')")
        c.commit()
        c.close()
        database.MIGRATIONS = old                          # the update
        database.migrate(db)
    finally:
        database.MIGRATIONS = old
    backups = list((tmp_path / "backups").glob("case-v5.db"))
    assert len(backups) == 1
    b = sqlite3.connect(backups[0])
    assert b.execute("SELECT title FROM cases").fetchone()[0] == "Fiktiver Fall"
    assert b.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 5
    b.close()
    c = database.connect(db)
    assert c.execute("SELECT title FROM cases").fetchone()[0] == "Fiktiver Fall"
    assert c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == \
        old[-1][0]
    c.close()
