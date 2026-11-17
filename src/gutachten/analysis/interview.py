# SPDX-License-Identifier: AGPL-3.0-or-later
"""Interview guide (Befragung) built from the Akte.

KSVI Anhang IV 3.2 asks for an in-depth interview including the "Besprechung von
Inkonsistenzen"; the EKQMB checks whether consistency is justified (E6). The guide
turns what the analysis found into questions — each with the reason and the source
(Bl.) — plus the standard topics. The expert decides what to ask; answers flow into
section "3. Befragung".

Deterministic: standard topics, findings (prior conditions, side, identity, dates),
treatment gaps, Beweisfragen. Optional model step: further clarifying questions per
Beweisfrage, each citing the entries it is based on.
"""
from __future__ import annotations

import json
import re
import sqlite3

from ..dates import find_dates
from ..llm.client import JsonLLM, LlmError
from .checks import region_of
from .common import call_llm

STANDARD = [
    ("jetziges_leiden", "Jetziges Leiden",
     "Welche Beschwerden haben Sie heute? Wie haben sie sich seit dem Ereignis entwickelt?"),
    ("unfallhergang", "Ereignis",
     "Wie hat sich das Ereignis genau zugetragen? Was haben Sie unmittelbar danach bemerkt?"),
    ("vorgeschichte", "Vorgeschichte",
     "Hatten Sie vor dem Ereignis Beschwerden, Behandlungen oder Unfälle an derselben Stelle?"),
    ("behandlungen", "Bisherige Behandlungen",
     "Welche Behandlungen und Medikamente haben Sie erhalten, und mit welchem Erfolg?"),
    ("arbeit", "Arbeit",
     "Welche Tätigkeit üben Sie aus? Was geht bei der Arbeit noch, was nicht mehr — und warum?"),
    ("alltag", "Tagesablauf und Alltag",
     "Wie sieht ein typischer Tag aus? Wobei brauchen Sie Hilfe? Hobbys, Sport, Haushalt?"),
    ("zukunft", "Zukunftsvorstellungen",
     "Wie sehen Sie Ihre gesundheitliche und berufliche Zukunft?"),
]

INTERVIEW_VERSION = "interview-guide-v1"
PROMPT = """\\
Du bereitest die Befragung einer versicherten Person für ein orthopädisches Gutachten vor.
Beweisfrage des Auftraggebers: {question}

Formuliere höchstens 3 kurze, offene Fragen an die versicherte Person, die Angaben
klären, welche für diese Beweisfrage wichtig sind und in der Akte unklar, widersprüchlich
oder lückenhaft sind. Keine Suggestivfragen, keine medizinischen Fachbegriffe, Sie-Form.
Jede Frage gibt in "refs" die Einträge an, aus denen sich der Klärungsbedarf ergibt, und
in "grund" kurz warum.

Belegte Einträge:
{entries}
"""
SCHEMA = {
    "type": "object",
    "properties": {"fragen": {"type": "array", "maxItems": 3, "items": {
        "type": "object",
        "properties": {"frage": {"type": "string", "maxLength": 300},
                       "grund": {"type": "string", "maxLength": 300},
                       "refs": {"type": "array", "items": {"type": "string"}, "maxItems": 4}},
        "required": ["frage", "grund", "refs"], "additionalProperties": False}}},
    "required": ["fragen"], "additionalProperties": False,
}


def _de(iso: str | None) -> str:
    if not iso:
        return ""
    y, *r = iso[:10].split("-")
    return ".".join([*reversed(r), y]) if r else y


def _src(c: dict | None) -> list[dict]:
    return [{"global_seq": c["global_seq"], "bbox": c.get("bbox")}] if c and c.get(
        "global_seq") else []


def build_guide(conn: sqlite3.Connection, case_id: str,
                llm: JsonLLM | None = None) -> list[dict]:
    guide: list[dict] = []

    def add(qid, topic, question, reason, origin, sources=()):
        guide.append({"id": qid, "topic": topic, "question": question, "reason": reason,
                      "origin": origin, "sources": list(sources)})

    for qid, topic, q in STANDARD:
        add(qid, topic, q, "Standardthema der Befragung (KSVI Anhang IV, 3.2)", "standard")

    for f in conn.execute(
            "SELECT * FROM findings WHERE case_id=? AND status!='rejected' ORDER BY id",
            (case_id,)):
        f = dict(f)
        a = json.loads(f["source_a"]) if f["source_a"] else None
        b = json.loads(f["source_b"]) if f["source_b"] else None
        srcs = _src(a) + _src(b)
        claim = f["claim"]
        if f["type"] == "predates_accident":
            region = region_of(claim) or "die betroffene Region"
            q = (f"In den Akten sind Beschwerden bzw. Befunde an {region.capitalize()} vor dem "
                 f"Ereignis dokumentiert. Hatten Sie damals Beschwerden? Seit wann, wie stark, "
                 f"mit welcher Behandlung — und wie war es unmittelbar vor dem Ereignis?")
        elif f["type"] == "laterality_conflict":
            q = ("In einem Bericht wird die andere Körperseite genannt. Welche Seite ist "
                 "betroffen — und haben Sie auch Beschwerden auf der anderen Seite?")
        elif f["type"] == "identity_mismatch":
            continue  # a question for the file, not for the person
        elif f["type"] == "coverage_gap":
            dates = [x.iso for x in find_dates(claim)] or re.findall(r"\d{4}-\d{2}-\d{2}", claim)
            span = " und ".join(_de(d) for d in dates[:2]) if dates else "zwei Behandlungen"
            q = (f"Zwischen {span} ist keine Behandlung dokumentiert. Wie ging es Ihnen in "
                 f"dieser Zeit? Haben Sie gearbeitet, Sport getrieben, Medikamente genommen?")
        elif f["type"] in ("date_contradiction", "causality_conflict"):
            q = (f"Zur Klärung eines Widerspruchs in den Akten: {claim}. Was ist Ihnen dazu "
                 f"erinnerlich?")
        else:
            q = f"Zur Klärung: {claim}"
        add(f"finding-{f['id']}", "Klärung aus der Akte", q, claim, "finding", srcs)

    for qrow in conn.execute("SELECT * FROM questions WHERE case_id=? ORDER BY ord", (case_id,)):
        add(f"beweis-{qrow['id']}", f"Beweisfrage {qrow['ord']}",
            "Angaben zu dieser Beweisfrage erfragen.", qrow["text"], "beweisfrage")
        if llm is not None:
            guide += _llm_questions(conn, case_id, llm, dict(qrow))
    return guide


def _llm_questions(conn, case_id, llm, q: dict) -> list[dict]:
    entries = [dict(r) for r in conn.execute(
        "SELECT * FROM timeline_entries WHERE case_id=? AND excluded=0 "
        "ORDER BY entry_date, sort", (case_id,))]
    if not entries:
        return []
    for i, e in enumerate(entries, 1):
        e["ref"] = f"E{i}"
        e["cites"] = json.loads(e["citations"] or "[]")
    text = "\n".join(f"[{e['ref']}] {_de(e['entry_date'])} · {e['title']}" for e in entries[:120])
    try:
        out = call_llm(conn, case_id, llm, stage="interview_guide", ref=f"frage {q['ord']}",
                       prompt_version=INTERVIEW_VERSION,
                       prompt=PROMPT.format(question=q["text"], entries=text),
                       schema=SCHEMA, max_tokens=1024)
    except LlmError:
        return []
    by = {e["ref"]: e for e in entries}
    res = []
    for i, f in enumerate(out.get("fragen", [])):
        cited = [by[r] for r in f.get("refs", []) if r in by]
        if not cited:
            continue  # no source, no question
        srcs = [{"global_seq": c["global_seq"], "bbox": c.get("bbox")}
                for e in cited for c in e["cites"][:1] if c.get("global_seq")]
        res.append({"id": f"llm-{q['id']}-{i}", "topic": f"Beweisfrage {q['ord']}",
                    "question": f["frage"], "reason": f["grund"], "origin": "llm",
                    "sources": srcs})
    return res


def render_befragung(interview: dict, guide_topics: dict[str, str], tpl: str) -> str | None:
    """Section text from the expert's answers; None if nothing was recorded."""
    spontan = (interview.get("spontan") or "").strip()
    answers = {k: v.strip() for k, v in (interview.get("answers") or {}).items() if v.strip()}
    if not spontan and not answers:
        return None
    iv = tpl == "iv"
    lines = ["### 3.1 Spontane Angaben der versicherten Person" if iv
             else "**Spontane Angaben:**", "",
             spontan or "[Spontane Angaben eintragen]", ""]
    if answers:
        lines += ["### 3.2 Vertiefende Befragung" if iv else "**Auf Nachfrage:**", ""]
        for qid, text in answers.items():
            lines.append(f"**{guide_topics.get(qid, 'Weitere Angaben')}:** {text}")
            lines.append("")
    return "\n".join(lines).rstrip()


# ------------------------------------------------------------------ indirect speech

INDIRECT_VERSION = "indirect-speech-v1"
INDIRECT_PROMPT = """\\
Formuliere die folgenden Notizen aus einer Befragung für ein Gutachten in sachliche
indirekte Rede um (Konjunktiv I, z. B. „Die versicherte Person gibt an, sie habe …“).
Nichts hinzufügen, nichts weglassen, nichts bewerten. Zahlen, Daten, Namen und
Körperseiten unverändert übernehmen.

Notizen:
{text}
"""
INDIRECT_SCHEMA = {"type": "object", "properties": {"text": {"type": "string",
                   "maxLength": 4000}}, "required": ["text"], "additionalProperties": False}
_TOKENS = re.compile(r"\d+(?:[.,:]\d+)*|\b(?:links|rechts|beidseits)\b", re.I)


def to_indirect(conn, case_id: str, llm: JsonLLM, text: str) -> dict:
    """Rewrite into indirect speech; warn if numbers, dates or sides changed."""
    out = call_llm(conn, case_id, llm, stage="indirect_speech", ref="befragung",
                   prompt_version=INDIRECT_VERSION, prompt=INDIRECT_PROMPT.format(text=text),
                   schema=INDIRECT_SCHEMA, max_tokens=2048)
    conn.commit()
    new = out.get("text", "").strip()
    before = sorted(t.lower() for t in _TOKENS.findall(text))
    after = sorted(t.lower() for t in _TOKENS.findall(new))
    return {"text": new, "changed_facts": before != after,
            "warning": None if before == after else
            "Zahlen, Daten oder Seitenangaben weichen ab — bitte vergleichen."}
