# SPDX-License-Identifier: AGPL-3.0-or-later
"""KI-Prüfung: content issues the rule checks cannot see.

The rules (checks.py) find identity, laterality, date and prior-condition issues.
Medical-content questions need reading comprehension: two reports that contradict
each other, a re-injury that may be a recurrence or a new lesion, an unclear
interval ("beschwerdefrei" vs. later complaints), a causal chain with a missing
link, a document that is referred to but missing, a late first report.

Same discipline as everywhere else:
- every issue cites the Aktenauszug entries it is based on (one or two); unknown
  entries or dates that are not in the cited entries -> the issue is dropped
  and logged, never shown;
- the issue states what is in the records and why it matters for the report —
  no judgement (the expert decides);
- marked as model output (created_by='ki'), kept apart from the rule findings, and
  the expert's decisions (accepted/rejected) survive every rerun.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from ..db import database
from ..llm.client import JsonLLM, LlmError
from .common import call_llm
from .drafting import _entries, _render_entries, _validate, de
from .proposals import _clean

VERSION = "ki-pruefung-v2"
TYPES = {
    "widerspruch": "Inhaltlicher Widerspruch",
    "vorschaden_abgrenzung": "Abgrenzung Vorschaden",
    "zwischenverlauf": "Unklarer Zwischenverlauf",
    "kausalkette": "Kausalkette",
    "fehlende_unterlage": "Fehlende Unterlage",
    "spaete_meldung": "Späte Meldung / Latenz",
}

PROMPT = """\\
Du prüfst eine Akte für ein orthopädisches Gutachten auf inhaltliche Auffälligkeiten,
die die Sachverständige kennen muss. Du beurteilst NICHT — du zeigst auf, was in den
Unterlagen steht und warum es für das Gutachten relevant ist.

Unfall-/Ereignisdatum: {accident}

Gesuchte Auffälligkeiten (type):
- widerspruch: zwei Unterlagen widersprechen sich inhaltlich (Befund, Diagnose,
  Hergang, Beschwerdebeginn, Beurteilung).
- vorschaden_abgrenzung: dieselbe Struktur war schon vorgeschädigt, verletzt oder
  operiert; ob ein Rezidiv/Folgezustand oder eine neue Läsion vorliegt, ist offen.
- zwischenverlauf: das Intervall zwischen zwei Ereignissen ist unklar (z. B.
  "beschwerdefrei" vs. später dokumentierte Beschwerden).
- kausalkette: eine Folge (Komplikation, Folgeoperation, Zweitschaden) hängt über
  eine Kette mit dem Ereignis zusammen; ein Glied ist belegt oder fehlt.
- fehlende_unterlage: eine Untersuchung/ein Bericht wird erwähnt, liegt aber nicht
  in der Akte (z. B. Bilder, OP-Bericht, Vorakte).
- spaete_meldung: auffällige Latenz zwischen Ereignis und erster Behandlung/Meldung.

Regeln:
- Höchstens 6 Auffälligkeiten, nur wirklich gutachtenrelevante. Kurze Intervalle
  (unter 2 Wochen) zwischen Ereignis und erster Behandlung sind NICHT auffällig.
- Wähle den passenden type: eine Folge über mehrere Schritte (z. B. OP → Thrombose →
  Lungenembolie) ist "kausalkette", kein "zwischenverlauf".
- Keine Eintragsnummern (E1 …) in "claim" — Fundstellen werden automatisch ergänzt.
- "refs_a" (Pflicht) und "refs_b" (falls zwei Unterlagen beteiligt): Einträge E…
- "claim": ein neutraler Satz, was in den Unterlagen steht. Daten nur genau so, wie
  sie in den zitierten Einträgen stehen. Keine Kausalitätsurteile.
- "relevance": ein Satz, welche Gutachtenfrage dadurch berührt wird.
- Nicht melden, was bereits unter "Bereits gefunden" steht.

Bereits gefunden:
{known}

Belegte Einträge:
{entries}
"""
_ISSUE = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": sorted(TYPES)},
        "claim": {"type": "string", "maxLength": 300},
        "relevance": {"type": "string", "maxLength": 250},
        "refs_a": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "refs_b": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["type", "claim", "relevance", "refs_a", "refs_b", "severity"],
    "additionalProperties": False,
}
SCHEMA = {"type": "object",
          "properties": {"issues": {"type": "array", "maxItems": 6, "items": _ISSUE}},
          "required": ["issues"], "additionalProperties": False}
JUDGEMENT = re.compile(r"überwiegend wahrscheinlich|ist (?:nicht )?unfallkausal|"
                       r"\bist (?:nicht )?kausal\b|adäqua", re.I)


def _cite(entry: dict) -> dict:
    c = dict((entry.get("cites") or [{}])[0])
    c.setdefault("quote", "")
    c["doc_title"] = c.get("doc_title") or entry["title"]
    return c


def _fp(type_: str, entries: list[dict]) -> str:
    key = "|".join(sorted(f"{e['entry_date']}:{e['title']}" for e in entries))
    return "ki:" + hashlib.sha1(f"{type_}|{key}".encode()).hexdigest()[:16]


def run_llm_checks(conn: sqlite3.Connection, case_id: str, llm: JsonLLM) -> dict:
    case = dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())
    accident = case.get("accident_date")
    entries = _entries(conn, case_id)  # insurer letters count here (e.g. "beschwerdefrei")
    if not entries:
        return {"findings": 0, "dropped": 0}
    by_ref = {e["ref"]: e for e in entries}
    known = [r["claim"] for r in conn.execute(
        "SELECT claim FROM findings WHERE case_id=? AND created_by!='ki'", (case_id,))]
    try:
        out = call_llm(conn, case_id, llm, stage="checks_ki", ref="Akte",
                       prompt_version=VERSION,
                       prompt=PROMPT.format(accident=de(accident) or "unbekannt",
                                            known="\n".join(f"- {k}" for k in known) or "–",
                                            entries=_render_entries(entries[:150])),
                       schema=SCHEMA, max_tokens=3072)
    except LlmError as e:
        database.audit(conn, case_id, "checks_ki_failed", str(e))
        conn.commit()
        return {"findings": 0, "dropped": 0, "error": str(e)}

    decided = {r["fingerprint"] for r in conn.execute(
        "SELECT fingerprint FROM findings WHERE case_id=? AND status!='open' "
        "AND fingerprint IS NOT NULL", (case_id,))}
    conn.execute("DELETE FROM findings WHERE case_id=? AND status='open' AND created_by='ki'",
                 (case_id,))
    new, dropped, seen = 0, [], set()
    for it in out.get("issues", []):
        claim = _clean(it.get("claim") or "")
        refs = [r for r in (it.get("refs_a") or []) + (it.get("refs_b") or [])]
        cited = [by_ref[r] for r in refs if r in by_ref]
        if not claim or not cited or len(cited) < len(refs):
            dropped.append(f"unbekannte Einträge: „{claim[:60]}“")
            continue
        _, problem = _validate(claim, refs, by_ref, (accident or "",))
        if problem:
            dropped.append(f"{problem}: „{claim[:60]}“")
            continue
        if JUDGEMENT.search(claim):
            dropped.append(f"enthält ein Urteil: „{claim[:60]}“")
            continue
        fp = _fp(it["type"], cited)
        if fp in decided or fp in seen:
            continue
        seen.add(fp)
        a = [by_ref[r] for r in it.get("refs_a") or [] if r in by_ref]
        b = [by_ref[r] for r in it.get("refs_b") or [] if r in by_ref]
        conn.execute(
            """INSERT INTO findings (case_id, type, severity, claim, source_a, source_b,
                                     explanation, fingerprint, created_by)
               VALUES (?,?,?,?,?,?,?,?, 'ki')""",
            (case_id, f"ki_{it['type']}", it.get("severity") or "medium", claim,
             json.dumps(_cite(a[0] if a else cited[0]), ensure_ascii=False),
             json.dumps(_cite(b[0]), ensure_ascii=False) if b else None,
             f"KI-Hinweis ({llm.model_id}): {it.get('relevance') or ''}".strip(), fp))
        new += 1
    database.audit(conn, case_id, "checks_ki",
                   f"{new} KI-Hinweise" + (f"; verworfen: {' | '.join(dropped)}" if dropped
                                            else ""))
    conn.commit()
    return {"findings": new, "dropped": len(dropped)}
