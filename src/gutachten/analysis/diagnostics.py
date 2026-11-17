# SPDX-License-Identifier: AGPL-3.0-or-later
"""Diagnosis of a case: what each stage produced and where information got lost.

Answers questions like "200 pages, only 3 results — why?" with numbers per stage:
pages with usable text, documents, extracted vs. verified statements (and why the
rest was rejected), model calls that failed, time per call, and which language model
build is running. Plain counts only; no patient content leaves this function except
short rejection reasons.
"""
from __future__ import annotations

import sqlite3
from collections import Counter

MIN_TEXT = 40  # characters — below this a page counts as "no usable text"


def case_diagnostics(conn: sqlite3.Connection, case_id: str) -> dict:
    q = lambda sql, *a: conn.execute(sql, (case_id, *a)).fetchall()  # noqa: E731
    pages = q("""SELECT p.global_seq, p.status, LENGTH(COALESCE(pt.text_md,'')) AS chars,
                        p.duplicate_of,
                        (SELECT engine FROM ocr_runs r WHERE r.page_id=p.id AND r.status='ok'
                         ORDER BY r.id DESC LIMIT 1) AS engine,
                        (SELECT error FROM ocr_runs r WHERE r.page_id=p.id
                         ORDER BY r.id DESC LIMIT 1) AS last_error
                 FROM pages p LEFT JOIN page_text pt ON pt.page_id=p.id
                 WHERE p.case_id=? ORDER BY p.global_seq""")
    n = len(pages)
    status = Counter(p["status"] for p in pages)
    empty = [p["global_seq"] for p in pages
             if p["status"] != "pending" and (p["chars"] or 0) < MIN_TEXT]
    ocr = {
        "pages": n,
        "pending": status.get("pending", 0),
        "review": status.get("review", 0),
        "done": n - status.get("pending", 0),
        "no_text": len(empty),
        "no_text_pages": empty[:30],
        "duplicates": sum(1 for p in pages if p["duplicate_of"]),
        "avg_chars": int(sum(p["chars"] or 0 for p in pages) / n) if n else 0,
        "engines": dict(Counter(p["engine"] or "—" for p in pages)),
        "errors": sum(1 for p in pages if p["last_error"]),
        "first_error": next((p["last_error"] for p in pages if p["last_error"]), None),
    }
    docs = q("SELECT doc_type, excluded, end_seq - start_seq + 1 AS n FROM documents "
             "WHERE case_id=?")
    documents = {"count": len(docs), "excluded": sum(d["excluded"] for d in docs),
                 "types": dict(Counter(d["doc_type"] for d in docs)),
                 "largest_pages": max((d["n"] or 0 for d in docs), default=0)}
    facts = q("SELECT verified, verify_note FROM facts WHERE case_id=?")
    reasons = Counter((f["verify_note"] or "").split(";")[0].split(":")[0].strip() or "—"
                      for f in facts if not f["verified"])
    extraction = {"statements": len(facts),
                  "verified": sum(1 for f in facts if f["verified"]),
                  "rejected": sum(1 for f in facts if not f["verified"]),
                  "reject_reasons": dict(reasons.most_common(6))}
    docs_without = q("""SELECT COUNT(*) FROM documents d WHERE d.case_id=? AND d.excluded=0
                        AND NOT EXISTS (SELECT 1 FROM facts f WHERE f.document_id=d.id)""")
    extraction["documents_without_statements"] = docs_without[0][0]
    calls = q("""SELECT stage, status, COUNT(*) n, CAST(AVG(duration_ms) AS INT) avg_ms,
                        MAX(duration_ms) max_ms
                 FROM llm_calls WHERE case_id=? GROUP BY stage, status""")
    model: dict[str, dict] = {}
    for c in calls:
        m = model.setdefault(c["stage"], {"ok": 0, "error": 0, "cache": 0, "avg_s": None,
                                           "max_s": None})
        m[c["status"]] = c["n"]
        if c["status"] == "ok":
            m["avg_s"] = round((c["avg_ms"] or 0) / 1000, 1)
            m["max_s"] = round((c["max_ms"] or 0) / 1000, 1)
    errors = [dict(r) for r in q("SELECT stage, ref, error FROM llm_calls WHERE case_id=? "
                                 "AND status='error' ORDER BY id DESC LIMIT 5")]
    out = {
        "ocr": ocr, "documents": documents, "extraction": extraction,
        "aktenauszug": q("SELECT COUNT(*) FROM timeline_entries WHERE case_id=? "
                         "AND excluded=0")[0][0],
        "findings": q("SELECT COUNT(*) FROM findings WHERE case_id=?")[0][0],
        "model_calls": model, "model_errors": errors,
    }
    out["hints"] = _hints(out)
    return out


def _hints(d: dict) -> list[str]:
    """Plain-language pointers to where results got lost."""
    h = []
    o, e, m = d["ocr"], d["extraction"], d["model_calls"]
    if o["pending"]:
        h.append(f"{o['pending']} Seite(n) noch ohne Texterkennung — Auswertung läuft "
                 "oder wurde unterbrochen.")
    if o["errors"]:
        h.insert(0, f"Texterkennung auf {o['errors']} Seite(n) fehlgeschlagen: "
                    f"{(o['first_error'] or '')[:160]}")
    if o["pages"] and o["no_text"] > 0.2 * o["pages"]:
        h.append(f"{o['no_text']} von {o['pages']} Seiten ohne verwertbaren Text — "
                 "Scanqualität oder Texterkennung prüfen (Reiter Akte, Seiten mit „prüfen“).")
    failed = sum(v.get("error", 0) for v in m.values())
    total = sum(v.get("ok", 0) + v.get("error", 0) for v in m.values())
    if failed and failed >= 0.1 * max(total, 1):
        h.append(f"{failed} von {total} Modellanfragen fehlgeschlagen — siehe "
                 "„Fehlgeschlagene Modellanfragen“ (häufig: Zeitüberschreitung ohne GPU).")
    slow = [k for k, v in m.items() if (v.get("avg_s") or 0) > 60]
    if slow:
        h.append("Modellanfragen sehr langsam (Ø über 60 s): das Sprachmodell läuft "
                 "vermutlich ohne Grafikkarte — Einrichtung → Grafikkarte prüfen.")
    if e["statements"] and e["rejected"] > e["verified"]:
        h.append(f"Mehr Angaben verworfen ({e['rejected']}) als belegt ({e['verified']}) — "
                 "meist Zitat nicht im OCR-Text gefunden (Texterkennung prüfen).")
    if d["documents"]["count"] and e["documents_without_statements"] > \
            0.5 * d["documents"]["count"]:
        h.append(f"{e['documents_without_statements']} von {d['documents']['count']} "
                 "Dokumenten ohne einzige Angabe.")
    if not h:
        h.append("Keine Auffälligkeiten in den Zahlen.")
    return h
