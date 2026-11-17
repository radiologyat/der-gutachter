# SPDX-License-Identifier: AGPL-3.0-or-later
"""Step states of a case: what ran when, what changed since, what is stale.

The workflow is a chain — Akte (OCR) → Dokumente → Aktenauszug → Hinweise →
Untersuchung → Gutachten → Freigabe. Each step records when it ran and when its
output last changed (by a run or a manual correction). A step is stale ("veraltet")
when something upstream changed after it ran; the UI then offers "ab hier neu
berechnen". Manual work is never lost by that: edited Aktenauszug entries and
edited draft sections survive every rerun.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

# internal steps and their inputs
UPSTREAM: dict[str, tuple[str, ...]] = {
    "ocr": (),
    "cover": ("ocr",),
    "index": ("ocr",),
    "extract": ("ocr", "index"),
    "timeline": ("extract", "index"),
    "checks": ("timeline",),
    "checks_ki": ("timeline",),
    "exam": (),
    "draft": ("timeline", "checks", "checks_ki", "exam", "cover"),
}
ORDER = ("ocr", "cover", "index", "extract", "timeline", "checks", "checks_ki", "exam", "draft")


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def mark_run(conn: sqlite3.Connection, case_id: str, step: str) -> None:
    t = _now()
    conn.execute("""INSERT INTO step_marks (case_id, step, ran_at, changed_at) VALUES (?,?,?,?)
                    ON CONFLICT(case_id, step) DO UPDATE SET ran_at=excluded.ran_at,
                    changed_at=excluded.changed_at""", (case_id, step, t, t))


def mark_changed(conn: sqlite3.Connection, case_id: str, step: str) -> None:
    conn.execute("""INSERT INTO step_marks (case_id, step, changed_at) VALUES (?,?,?)
                    ON CONFLICT(case_id, step) DO UPDATE SET changed_at=excluded.changed_at""",
                 (case_id, step, _now()))


def stale(conn: sqlite3.Connection, case_id: str) -> dict[str, list[str]]:
    """step -> upstream steps that changed after it ran (transitively)."""
    marks = {r["step"]: dict(r) for r in conn.execute(
        "SELECT * FROM step_marks WHERE case_id=?", (case_id,))}
    out: dict[str, list[str]] = {}
    for step in ORDER:
        ran = (marks.get(step) or {}).get("ran_at")
        if not ran:
            continue
        why = [u for u in UPSTREAM[step]
               if u in out or ((marks.get(u) or {}).get("changed_at") or "") > ran]
        if why:
            out[step] = why
    return out


def recompute_from(step: str, with_vorentwurf: bool) -> list[str]:
    """Analysis steps to rerun from `step` (runner names, canonical order)."""
    chain = ["index", "extract", "timeline", "checks", "checks_ki", "draft"]
    start = {"ocr": "index", "cover": "index", "exam": "draft"}.get(step, step)
    steps = chain[chain.index(start):] if start in chain else ["draft"]
    return steps + (["vorentwurf"] if with_vorentwurf and "draft" in steps else [])


def overview(conn: sqlite3.Connection, case_id: str) -> dict:
    """The seven user-facing steps with state and the next thing to do."""
    st = stale(conn, case_id)
    marks = {r["step"]: dict(r) for r in conn.execute(
        "SELECT * FROM step_marks WHERE case_id=?", (case_id,))}
    one = lambda sql: conn.execute(sql, (case_id,)).fetchone()  # noqa: E731
    pages = one("SELECT COUNT(*) n, COALESCE(SUM(status='pending'),0) p, "
                "COALESCE(SUM(status='review'),0) r FROM pages WHERE case_id=? "
                "AND duplicate_of IS NULL")
    docs = one("SELECT COUNT(*) n FROM documents WHERE case_id=?")
    ent = one("SELECT COUNT(*) n, COALESCE(SUM(reviewed=0 AND excluded=0),0) u, "
              "COALESCE(SUM(created_by!='pipeline' OR edited=1),0) m, "
              "COALESCE(SUM(excluded),0) x FROM timeline_entries WHERE case_id=?")
    fnd = one("SELECT COUNT(*) n, COALESCE(SUM(status='open'),0) o, "
              "COALESCE(SUM(status='open' AND created_by='ki'),0) k FROM findings "
              "WHERE case_id=?")
    case = dict(one("SELECT exam_json, interview_json FROM cases WHERE id=?"))
    secs = [dict(r) for r in conn.execute(
        "SELECT status, content_md FROM draft_sections WHERE case_id=?", (case_id,))]
    exam = bool(json.loads(case.get("exam_json") or "{}")) or bool(
        json.loads(case.get("interview_json") or "{}"))
    ki = sum(s["content_md"].count("⟦KI⟧") for s in secs)

    def item(key, label, tab, state, detail, internal=()):
        why = sorted({u for s in internal for u in st.get(s, [])})
        if why and state not in ("offen", "läuft"):
            state = "veraltet"
            first = next(s for s in ORDER if s in st)  # earliest stale step overall
            return {"key": key, "label": label, "tab": tab, "state": state, "detail": detail,
                    "stale_because": why, "recompute": recompute_from(
                        first, "vorentwurf" in marks)}
        return {"key": key, "label": label, "tab": tab, "state": state, "detail": detail}

    items = [
        item("akte", "Akte", "akte",
             "offen" if not pages["n"] else "läuft" if pages["p"] else
             "prüfen" if pages["r"] else "ok",
             f"{pages['n']} Seiten" + (f", {pages['p']} ohne Texterkennung" if pages["p"]
                                       else "") + (f", {pages['r']} zu prüfen" if pages["r"]
                                                   else "")),
        item("dokumente", "Dokumente", "register", "ok" if docs["n"] else "offen",
             f"{docs['n']} Dokumente", ("index", "cover")),
        item("auszug", "Aktenauszug", "auszug",
             "offen" if not ent["n"] else "prüfen" if ent["u"] else "ok",
             f"{ent['n']} Einträge, {ent['u']} ungeprüft"
             + (f", {ent['m']} manuell" if ent["m"] else "")
             + (f", {ent['x']} ausgeschlossen" if ent["x"] else ""),
             ("extract", "timeline")),
        item("hinweise", "Hinweise", "hinweise",
             "offen" if "checks" not in marks else "prüfen" if fnd["o"] else "ok",
             f"{fnd['o']} offen von {fnd['n']}"
             + (f", davon {fnd['k']} KI" if fnd["k"] else ""), ("checks", "checks_ki")),
        item("untersuchung", "Untersuchung", "untersuchung", "ok" if exam else "offen",
             "erfasst" if exam else "Befragung und Befund fehlen"),
        item("gutachten", "Gutachten", "gutachten",
             "offen" if not secs else "prüfen" if ki else "ok",
             f"{len(secs)} Abschnitte" + (f", {ki} KI-Vorschläge zu prüfen" if ki else ""),
             ("draft",)),
        item("freigabe", "Freigabe", "gutachten",
             "ok" if secs and all(s["status"] == "approved" for s in secs) else "offen",
             f"{sum(s['status'] == 'approved' for s in secs)} von {len(secs)} freigegeben"),
    ]
    # what is still missing, in plain words, in workflow order
    todo = []
    if pages["p"]:
        todo.append(("akte", f"Texterkennung von {pages['p']} Seite(n) ausstehend"))
    if pages["r"]:
        todo.append(("akte", f"{pages['r']} unsichere Seite(n) prüfen"))
    if not docs["n"] and pages["n"]:
        todo.append(("register", "Akte auswerten (Register, Angaben, Aktenauszug)"))
    if ent["u"]:
        todo.append(("auszug", f"{ent['u']} Aktenauszug-Einträge prüfen"))
    if fnd["o"]:
        todo.append(("hinweise", f"{fnd['o']} Hinweise bestätigen oder verwerfen"))
    if not exam:
        todo.append(("untersuchung", "Befragung und Untersuchungsbefund erfassen"))
    if ki:
        todo.append(("gutachten", f"{ki} KI-Vorschläge prüfen (übernehmen oder umschreiben)"))
    open_secs = sum(s["status"] != "approved" for s in secs)
    if secs and open_secs:
        todo.append(("gutachten", f"{open_secs} von {len(secs)} Abschnitten freigeben"))
    if not secs and ent["n"]:
        todo.append(("gutachten", "Gutachten-Entwurf erstellen"))
    for i in items:
        if i["state"] == "veraltet":
            todo.insert(0, (i["tab"], f"{i['label']} ist veraltet – „Alles aktualisieren“"))
    done = sum(1 for i in items if i["state"] == "ok")
    return {"steps": items, "stale": st,
            "progress": {"done": done, "total": len(items),
                         "pct": round(100 * done / len(items)) if items else 0},
            "todo": [{"tab": t, "text": x} for t, x in todo]}


# Manual corrections (API path -> step whose output they change)
_MANUAL = [
    (r"/pages/\d+/text$", "ocr"),
    (r"/documents/", "index"),
    (r"/(?:suggestions|dates)(?:/|$)", "cover"),
    (r"/timeline(?:/|$)", "timeline"),
    (r"/findings/", "checks"),
    (r"/(?:exam|answers|interview|diagnoses|questions)(?:/|$)", "exam"),
]


def manual_change_step(path: str) -> tuple[str, str] | None:
    """-> (case_id, step) for a manual correction request, else None."""
    import re

    m = re.match(r"^/api/cases/([^/]+)(/.*)$", path)
    if not m or m.group(2).endswith(("/analyze", "/intake", "/ocr", "/files")):
        return None
    if re.search(r"/reviewed$", m.group(2)):
        return None  # marking as checked changes nothing downstream
    if re.search(r"/interview/indirect$", m.group(2)):
        return None  # a conversion helper, nothing stored
    for pattern, step in _MANUAL:
        if re.search(pattern, m.group(2)):
            return m.group(1), step
    if m.group(2) == "" or m.group(2) == "/":
        return m.group(1), "cover"  # case details (accident date, client …)
    return None


def touch(case_id: str, step: str) -> None:
    from ..cases import connect_case

    try:
        conn = connect_case(case_id)
    except Exception:  # noqa: BLE001 — unknown case: the route already answered
        return
    try:
        mark_changed(conn, case_id, step)
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ "Alles aktualisieren"

CHAIN = ("index", "extract", "timeline", "checks", "checks_ki", "draft")


def plan_refresh(conn: sqlite3.Connection, case_id: str, vorentwurf: bool) -> list[str]:
    """The analysis steps a one-click refresh has to run, in order: steps that never ran
    or are stale, and everything after the first of them. Steps that are up to date are
    skipped. (The cover is handled separately: read once, never automatically again,
    so undone suggestions are not re-applied.)"""
    st = stale(conn, case_id)
    marks = {r["step"]: dict(r) for r in conn.execute(
        "SELECT * FROM step_marks WHERE case_id=?", (case_id,))}
    pages = conn.execute("SELECT COUNT(*) FROM pages WHERE case_id=?", (case_id,)).fetchone()[0]
    if not pages:
        return []
    steps: list[str] = []
    for step in CHAIN:
        if steps or step in st or not (marks.get(step) or {}).get("ran_at"):
            steps.append(step)
    if vorentwurf and ("draft" in steps or not (marks.get("vorentwurf") or {}).get("ran_at")):
        steps.append("vorentwurf")
    return steps
