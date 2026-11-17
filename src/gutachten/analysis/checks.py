# SPDX-License-Identifier: AGPL-3.0-or-later
"""Widerspruchsanalyse (Phase 3): deterministic rules over documents and facts.

Every finding cites both sides (source_a / source_b) so the physician sees the
conflict in the original. Findings are hints for the expert, never conclusions;
e.g. a Vorbefund before the accident is reported as a note, not as an error.

Rules
  identity_mismatch   patient name / DOB on a document differs from the case
                      (other person -> 'fremdes Dokument', else typo/Verwechslung)
  predates_accident   finding at the injured region documented before the accident
  causality_conflict  fact labelled 'unfallkausal' but dated before the accident,
                      or concerning the other side
  laterality_conflict same region, opposite side to the accident after the accident
  date_contradiction  the same procedure reported with different dates
  implausible_date    date before birth or in the future

Re-runs keep the user's decisions: each finding has a stable fingerprint; a
decided (accepted/rejected) fingerprint is not raised again.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
from collections import Counter
from difflib import SequenceMatcher

from ..citations import locate_quote, normalize
from ..dates import normalize_iso
from ..db import database

REGIONS = {
    "knie": ("knie", "menisk", "kreuzband", "vkb", "hkb", "patella", "gonarthr"),
    "schulter": ("schulter", "rotatoren", "acromi", "akromi", "humeruskopf"),
    "hüfte": ("hüft", "huft", "coxarthr", "koxarthr", "hueft"),
    "sprunggelenk": ("sprunggelenk", "osg", "usg", "achillessehne"),
    "wirbelsäule": ("lws", "bws", "hws", "wirbels", "lumb", "rücken", "ruecken", "bandscheib"),
    "hand": ("hand", "handgelenk", "finger", "radius"),
    "ellbogen": ("ellbogen", "ellenbogen", "epicondyl"),
    "fuss": ("fuss", "fuß", "mittelfuss", "zehe"),
}
OPPOSITE = {"links": "rechts", "rechts": "links"}
SIDE_WORDS = re.compile(r"\b(li|re|links|rechts|linke[snrm]?|rechte[snrm]?|bds|beidseits)\b\.?")


def region_of(*texts: str | None) -> str | None:
    t = " ".join(normalize(x) for x in texts if x)
    for region, stems in REGIONS.items():
        if any(s in t for s in stems):
            return region
    return None


def _name_key(name: str | None) -> str:
    """'Muster Max' == 'Max Muster' == 'Herr Max Muster'."""
    words = re.findall(r"[a-zäöüß]+", normalize(name or ""))
    words = [w for w in words if w not in {"herr", "frau", "dr", "med", "patient", "patientin"}]
    return " ".join(sorted(words))


# values the model writes when it cannot read a name — they are no names
_NAME_PLACEHOLDERS = {"null", "none", "unbekannt", "n/a", "na", "-", "–", "—", "?", "x"}


def _has_name(name: str | None) -> bool:
    return bool(name) and _name_key(name) not in _NAME_PLACEHOLDERS


def _names_compatible(a: str, b: str) -> bool:
    """True if the shorter name is contained in the longer one, initials allowed:
    "widmer" / "d widmer" vs "daniel widmer"."""
    small, big = sorted((a.split(), b.split()), key=len)

    def covered(tok: str) -> bool:
        return any(t == tok or (len(tok) == 1 and t.startswith(tok)) for t in big)

    return all(covered(t) for t in small)


def _fp(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def _fact_cite(f: dict) -> dict:
    return {"page_id": f["page_id"], "global_seq": f["global_seq"], "fact_id": f["id"],
            "block_ids": json.loads(f["block_ids"] or "[]"),
            "bbox": json.loads(f["bbox"]) if f["bbox"] else None,
            "quote": f["quote"], "doc_title": f["doc_title"]}


def _doc_cite(conn, d: dict, text: str | None) -> dict:
    page = conn.execute(
        "SELECT id FROM pages WHERE case_id=? AND global_seq=?", (d["case_id"], d["start_seq"])
    ).fetchone()
    c = locate_quote(conn, [page["id"]], text, min_score=0.8) if page and text else None
    return {"page_id": page["id"] if page else None, "global_seq": d["start_seq"],
            "block_ids": c.block_ids if c else [], "bbox": list(c.bbox) if c and c.bbox else None,
            "quote": text or "", "doc_title": d["title"], "document_id": d["id"]}


class _Collector:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, type_, severity, claim, a, b=None, explanation="", document_id=None, key=()):
        self.items.append({"type": type_, "severity": severity, "claim": claim,
                           "source_a": a, "source_b": b, "explanation": explanation,
                           "document_id": document_id, "fingerprint": _fp(type_, *key)})


# ------------------------------------------------------------------ reference identity

def reference_identity(case: dict, docs: list[dict]) -> tuple[str | None, str | None]:
    """Case DOB if set, else the majority across documents; same for the name."""
    names = Counter(_name_key(d["patient_name"]) for d in docs if _has_name(d["patient_name"]))
    dobs = Counter(d["patient_dob"] for d in docs if d["patient_dob"])
    dob = normalize_iso(case.get("patient_dob")) or (dobs.most_common(1)[0][0] if dobs else None)
    name = names.most_common(1)[0][0] if names else None
    return name, dob


def check_identity(conn, case, docs, out: _Collector) -> None:
    ref_name, ref_dob = reference_identity(case, docs)
    for d in docs:
        if d["excluded"]:
            continue
        name_k = _name_key(d["patient_name"]) if _has_name(d["patient_name"]) else None
        # "Widmer" or "D. Widmer" for "Daniel Widmer" is the same person, not a mismatch
        partial = bool(name_k and ref_name and _names_compatible(name_k, ref_name))
        name_diff = bool(ref_name and name_k and name_k != ref_name and not partial)
        name_sim = SequenceMatcher(None, name_k or "", ref_name or "").ratio() if name_diff else 1
        dob_diff = bool(ref_dob and d["patient_dob"] and d["patient_dob"] != ref_dob)
        if not (name_diff or dob_diff):
            continue
        shown = d["patient_name"] or ""
        if d["patient_dob"]:
            shown += f", geb. {d['patient_dob']}"
        quote = d["patient_name"] or ""
        # A typo changes one part of a date (1961 -> 1963); another person differs
        # in several. Clearly different names always mean another person.
        dob_a = (d["patient_dob"] or "").split("-")
        dob_b = (ref_dob or "").split("-")
        dob_parts_diff = sum(x != y for x, y in zip(dob_a, dob_b, strict=False)) if dob_diff else 0
        other_person = (name_diff and name_sim < 0.7) or dob_parts_diff >= 2 or (
            name_diff and dob_diff and name_sim < 0.6)
        if other_person:
            out.add("identity_mismatch", "high",
                    f"Dokument betrifft möglicherweise eine andere Person: {shown}",
                    _doc_cite(conn, d, quote), None,
                    "Name weicht deutlich vom Probanden ab"
                    + (" und Geburtsdatum ebenfalls" if dob_diff else "")
                    + ". Falls fremdes Dokument: aus der Auswertung ausschliessen.",
                    document_id=d["id"], key=(d["id"], name_k, d["patient_dob"]))
        else:
            parts = []
            if name_diff:
                parts.append(f"Name „{d['patient_name']}“")
            if dob_diff:
                parts.append(f"Geburtsdatum {d['patient_dob']} statt {ref_dob}")
            out.add("identity_mismatch", "medium",
                    "Abweichende Personalien: " + ", ".join(parts),
                    _doc_cite(conn, d, quote), None,
                    "Vermutlich Schreib- oder Übertragungsfehler im Dokument — "
                    "Zuordnung zum Probanden prüfen.",
                    document_id=d["id"], key=(d["id"], name_k, d["patient_dob"]))


# ------------------------------------------------------------------ accident anchor

def accident_anchor(facts: list[dict], accident: str | None) -> tuple[str | None, str | None]:
    """(region, side) of the accident from trauma/unfallkausal facts on/after the date."""
    pool = [f for f in facts if accident and f["fact_date"] and f["fact_date"][:10] == accident
            and f["event_category"] in ("trauma", "diagnostik")]
    pool = pool or [f for f in facts if f["causality"] == "unfallkausal"]
    regions = Counter(r for f in pool if (r := region_of(f["body_region"], f["title"])))
    sides = Counter(f["laterality"] for f in pool if f["laterality"] in OPPOSITE)
    return (regions.most_common(1)[0][0] if regions else None,
            sides.most_common(1)[0][0] if sides else None)


def check_timeline_rules(conn, case, facts, out: _Collector) -> None:
    accident = normalize_iso(case.get("accident_date"))
    region, side = accident_anchor(facts, accident)
    anchor = next((f for f in facts if accident and f["fact_date"]
                   and f["fact_date"][:10] == accident
                   and f["event_category"] == "trauma"), None)
    today = dt.date.today().isoformat()
    dob = normalize_iso(case.get("patient_dob"))

    for f in facts:
        d = f["fact_date"]
        if not d:
            continue
        f_region = region_of(f["body_region"], f["title"], f["summary"])
        same_region = region is not None and f_region == region
        before = accident is not None and d < accident and not accident.startswith(d)

        if d > today or (dob and d < dob):
            out.add("implausible_date", "medium",
                    f"Unplausibles Datum {d}: " + ("in der Zukunft" if d > today
                                                   else "vor der Geburt"),
                    _fact_cite(f), None, "Lese- oder Tippfehler im Dokument oder in der OCR?",
                    key=(f["id"],))
        if before and f["causality"] == "unfallkausal":
            out.add("causality_conflict", "high",
                    f"Als unfallkausal markiert, aber vor dem Unfall ({accident}) dokumentiert:"
                    f" {f['title']}", _fact_cite(f), _fact_cite(anchor) if anchor else None,
                    "Ein Befund vor dem Ereignis kann nicht Unfallfolge sein — "
                    "Einordnung als Vorzustand prüfen.", key=(f["id"],))
        elif before and same_region and f["laterality"] in (side, "beidseits", "na", None):
            out.add("predates_accident", "medium",
                    f"Vorbefund {f_region.capitalize()} vor dem Unfall: {f['title']} ({d})",
                    _fact_cite(f), _fact_cite(anchor) if anchor else None,
                    "Dokumentierter Befund an der verletzten Region vor dem Ereignis — "
                    "relevant für die Abgrenzung Vorzustand / Unfallfolge.", key=(f["id"],))
        if (not before and side and same_region
                and f["laterality"] == OPPOSITE[side]):
            sev = "high" if f["causality"] == "unfallkausal" else "medium"
            out.add("laterality_conflict", sev,
                    f"Seitenangabe {f['laterality']} statt {side}: {f['title']} ({d})",
                    _fact_cite(f), _fact_cite(anchor) if anchor else None,
                    f"Das Ereignis betraf {region.capitalize()} {side}. "
                    + ("Als unfallkausal markiert — Seite prüfen. " if sev == "high" else "")
                    + "Verwechslung der Seite oder neues Beschwerdebild?", key=(f["id"],))


def check_documented_prior_condition(case, facts, out: _Collector) -> None:
    """Prior conditions the record states without an earlier date ("schon vorher",
    "seit 3-4 Jahren progredient"): the fact carries the document date or none,
    so the date rule cannot see it — the model's 'vorschaden' label can."""
    accident = normalize_iso(case.get("accident_date"))
    region, _side = accident_anchor(facts, accident)
    anchor = next((f for f in facts if accident and f["fact_date"]
                   and f["fact_date"][:10] == accident
                   and f["event_category"] == "trauma"), None)
    for f in facts:
        if f["causality"] != "vorschaden":
            continue
        # 'vorschaden' on a non-clinical entry is a verdict about causality
        # (insurance/court decision, correspondence), not a documented finding
        if f["event_category"] in {"trauma", "begutachtung", "korrespondenz",
                                 "arbeitsfaehigkeit"}:
            continue
        d = f["fact_date"]
        if accident and d and d < accident and not accident.startswith(d):
            continue  # already reported by the date rule
        f_region = region_of(f["body_region"], f["title"], f["summary"], f["quote"])
        if region and f_region != region:
            continue
        out.add("predates_accident", "medium",
                f"Vorzustand laut Akte: {f['title']}",
                _fact_cite(f), _fact_cite(anchor) if anchor else None,
                "In der Akte als vorbestehend beschrieben (ohne früheres Datum) — "
                "relevant für die Abgrenzung Vorzustand / Unfallfolge.", key=(f["id"],))


GAP_DAYS = 90
CARE = {"op", "konservativ", "reha", "diagnostik", "arbeitsfaehigkeit"}


def treatment_gaps(case: dict, facts: list[dict]) -> list[tuple[dict, dict, int]]:
    """Intervals after the accident without any documented care (> GAP_DAYS).
    A long gap followed by renewed treatment is relevant for causality
    ("behandlungsfreies Intervall")."""
    accident = normalize_iso(case.get("accident_date"))
    care = sorted((f for f in facts if f["event_category"] in CARE and f["fact_date"]
                   and len(f["fact_date"]) == 10
                   and (not accident or f["fact_date"] >= accident)),
                  key=lambda f: f["fact_date"])
    gaps = []
    for a, b in zip(care, care[1:], strict=False):
        days = (dt.date.fromisoformat(b["fact_date"]) - dt.date.fromisoformat(a["fact_date"])).days
        if days > GAP_DAYS:
            gaps.append((a, b, days))
    return gaps


def check_treatment_gaps(case, facts, out: _Collector) -> None:
    for a, b, days in treatment_gaps(case, facts):
        out.add("coverage_gap", "low",
                f"Keine Behandlung dokumentiert zwischen {a['fact_date']} und {b['fact_date']} "
                f"(rund {round(days / 30)} Monate)",
                _fact_cite(a), _fact_cite(b),
                "Behandlungsfreies Intervall — für die Beurteilung des Verlaufs und der "
                "Kausalität relevant; in der Befragung klären.", key=(a["id"], b["id"]))


def check_procedure_dates(facts, out: _Collector) -> None:
    """Same procedure (category op, same region/side, similar title) on different
    dates in different documents, within 60 days of each other."""
    ops = [f for f in facts if f["event_category"] == "op" and f["fact_date"]
           and len(f["fact_date"]) == 10]
    for i, a in enumerate(ops):
        for b in ops[i + 1:]:
            if a["document_id"] == b["document_id"] or a["fact_date"] == b["fact_date"]:
                continue
            if (a["laterality"] or "na") != (b["laterality"] or "na"):
                continue
            if region_of(a["title"], a["body_region"]) != region_of(b["title"], b["body_region"]):
                continue
            ta = SIDE_WORDS.sub("", normalize(a["title"]))
            tb = SIDE_WORDS.sub("", normalize(b["title"]))
            if SequenceMatcher(None, ta, tb).ratio() < 0.6:
                continue
            gap = abs((dt.date.fromisoformat(a["fact_date"])
                       - dt.date.fromisoformat(b["fact_date"])).days)
            if gap > 60:
                continue  # plausibly a second operation
            x, y = sorted((a, b), key=lambda f: f["id"])
            out.add("date_contradiction", "medium",
                    f"{a['title']}: {a['fact_date']} vs. {b['fact_date']}",
                    _fact_cite(a), _fact_cite(b),
                    f"Derselbe Eingriff mit unterschiedlichem Datum ({gap} Tage Abstand) — "
                    "OP-Bericht ist massgeblich.", key=(x["id"], y["id"]))


# ------------------------------------------------------------------ runner

def run_checks(conn: sqlite3.Connection, case_id: str) -> dict:
    case = dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())
    docs = [dict(r) for r in conn.execute(
        "SELECT * FROM documents WHERE case_id=? ORDER BY start_seq", (case_id,))]
    facts = [dict(r) for r in conn.execute(
        """SELECT f.*, p.global_seq, d.title AS doc_title
           FROM facts f JOIN pages p ON p.id=f.page_id
           JOIN documents d ON d.id=f.document_id
           WHERE f.case_id=? AND f.verified=1 AND d.excluded=0
           ORDER BY f.fact_date, p.global_seq""", (case_id,))]

    out = _Collector()
    check_identity(conn, case, docs, out)
    check_timeline_rules(conn, case, facts, out)
    check_documented_prior_condition(case, facts, out)
    check_procedure_dates(facts, out)
    check_treatment_gaps(case, facts, out)

    decided = {r["fingerprint"] for r in conn.execute(
        "SELECT fingerprint FROM findings WHERE case_id=? AND status!='open'"
        " AND fingerprint IS NOT NULL", (case_id,))}
    conn.execute("DELETE FROM findings WHERE case_id=? AND status='open'"
                 " AND created_by='pipeline'", (case_id,))
    seen, new = set(), 0
    for f in out.items:
        if f["fingerprint"] in decided or f["fingerprint"] in seen:
            continue
        seen.add(f["fingerprint"])
        conn.execute(
            """INSERT INTO findings (case_id, type, severity, claim, source_a, source_b,
                                     explanation, fingerprint, document_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (case_id, f["type"], f["severity"], f["claim"],
             json.dumps(f["source_a"], ensure_ascii=False),
             json.dumps(f["source_b"], ensure_ascii=False) if f["source_b"] else None,
             f["explanation"], f["fingerprint"], f["document_id"]),
        )
        new += 1
    by_type = Counter(f["type"] for f in out.items if f["fingerprint"] in seen)
    database.audit(conn, case_id, "checks_run",
                   f"{new} offene Hinweise: " + ", ".join(f"{k} {v}" for k, v in by_type.items()))
    conn.commit()
    return {"findings": new, "by_type": dict(by_type), "kept_decisions": len(decided)}
