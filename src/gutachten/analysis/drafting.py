# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gutachten-Entwurf (Phase 4): sections from verified material only.

Principle: the software prepares, the expert decides.
  data       deterministic from the database (no AI): Auftrag, Grundlagen, Diagnosen
  narrative  AI prose from verified Aktenauszug entries; every sentence must cite
             entries; sentences without valid citation or with dates not found in
             the cited entries are marked ⚠ and block approval
  basis      AI groups verified entries into "für Unfall / für Vorzustand / offen" —
             never a conclusion; the medical judgement is a placeholder for the expert
  questions  per Beweisfrage: relevant case material (basis), answer left to the expert
  manual     written by the expert (eigene Anamnese, Untersuchungsbefund)

Approval is refused while ⚠ marks or "[…]" placeholders remain. Approved sections
are never overwritten by regeneration.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3

from ..dates import find_dates
from ..db import database
from ..llm.client import JsonLLM, LlmError
from ..llm.prompts import BASIS_PROMPT, BASIS_VERSION, NARRATIVE_PROMPT, NARRATIVE_VERSION
from ..llm.schemas import BASIS_SCHEMA, NARRATIVE_SCHEMA
from . import report_sections as rs
from .common import call_llm

WARN = "⚠"
PLACEHOLDER = re.compile(r"\[(?:[^\]]*?(?:eintragen|formulieren|Ihre Antwort)[^\]]*)\]")
CHUNK_ENTRIES = 40

EXPERT_JUDGEMENT = "**Ärztliche Beurteilung:** [durch die/den Sachverständige/n zu formulieren]"


def de(iso: str | None) -> str:
    if not iso:
        return "—"
    y, *rest = iso[:10].split("-")
    return ".".join([*reversed(rest), y]) if rest else y


def _bl(seqs) -> str:
    s = sorted(set(seqs))
    return f"(Bl. {', '.join(map(str, s))} d. A.)" if s else ""


# ------------------------------------------------------------------ material

# Insurer rulings, assignments and correspondence are not medical evidence (a model
# would otherwise argue "Leistungen sistiert → Kausalität unklar" and take over the
# insurer's legal presumption). They stay in the Aktenauszug only.
NON_MEDICAL = {"begutachtung", "korrespondenz"}

# Insurer decisions and legal concepts are not medical arguments
NON_MEDICAL_ARG = re.compile(
    r"adäqua|listendiagnose|vermutung de[rs] (?:unfall)?kausalität|gegenbeweis|\bsistier|"
    r"verfügung|leistungspflicht|leistungen (?:wurden|werden|sind)|einsprache|"
    r"invalidität|erwerbsunfähig", re.I)

ADEQUACY_NOTE = ("*Hinweis: Die Adäquanz ist eine Rechtsfrage und wird vom Versicherer bzw. "
                 "Gericht beurteilt; ärztlich wird nur zur natürlichen Kausalität Stellung "
                 "genommen.*")
ADEQUACY = re.compile(r"adäqua", re.I)


def swiss(text: str, tpl: str) -> str:
    """Swiss reports use ss, never ß (model output is often German-German)."""
    return text if tpl == "at" else text.replace("ß", "ss")


NON_MEDICAL_DOCS = {"versicherung", "gericht"}


def _is_medical(entry: dict, doc_types: dict[int, str]) -> bool:
    """Decided by the source documents, not the event category: a clinic's statement
    is filed as "begutachtung" like the insurer's ruling, but it is medical evidence
    (e.g. a surgeon's view opposing the insurer's file review)."""
    types = {doc_types.get(c.get("fact_id")) for c in json.loads(entry["citations"] or "[]")
             if c.get("fact_id")} - {None}
    if types:
        return not types <= NON_MEDICAL_DOCS
    return entry["category"] not in NON_MEDICAL  # manual entry without source


def _entries(conn, case_id: str, categories: set[str] | None = None,
             medical_only: bool = False) -> list[dict]:
    rows = []
    doc_types = {r[0]: r[1] for r in conn.execute(
        "SELECT f.id, d.doc_type FROM facts f JOIN documents d ON d.id=f.document_id "
        "WHERE f.case_id=?", (case_id,))} if medical_only else {}
    for r in conn.execute(
        "SELECT * FROM timeline_entries WHERE case_id=? AND excluded=0 "
        "ORDER BY entry_date, sort", (case_id,)
    ):
        d = dict(r)
        if categories and d["category"] not in categories:
            continue
        if medical_only and not _is_medical(d, doc_types):
            continue
        d["cites"] = json.loads(d["citations"] or "[]")
        rows.append(d)
    for i, d in enumerate(rows, start=1):
        d["ref"] = f"E{i}"
    return rows


def _render_entries(entries: list[dict]) -> str:
    out = []
    for e in entries:
        quotes = "; ".join(f'„{c["quote"]}“' for c in e["cites"][:3] if c.get("quote"))
        span = de(e["entry_date"]) + (f"–{de(e['date_end'])}" if e.get("date_end") else "")
        out.append(f"[{e['ref']}] {span} · {e['category'] or '—'} · {e['title']}"
                   + (f" — {e['summary']}" if e.get("summary") and e["summary"] != e["title"]
                      else "") + (f"\n     Zitat: {quotes}" if quotes else ""))
    return "\n".join(out)


def _validate(text: str, refs: list[str], by_ref: dict[str, dict],
              extra_dates: tuple[str, ...] = ()) -> tuple[list[int], str | None]:
    """-> (Bl. numbers, problem or None). A sentence needs >= 1 known ref, and every
    date it states must belong to a cited entry (date, end date or quoted text)."""
    known = [by_ref[r] for r in refs if r in by_ref]
    if not known:
        return [], "ohne gültigen Beleg"
    seqs = [c["global_seq"] for e in known for c in e["cites"] if c.get("global_seq")]
    allowed = " ".join(
        f"{e['entry_date']} {e.get('date_end') or ''} "
        + " ".join(c.get("quote") or "" for c in e["cites"]) for e in known)
    allowed_iso = {f.iso for f in find_dates(allowed)} | {
        e["entry_date"][:10] for e in known} | {
        (e.get("date_end") or "")[:10] for e in known} | {d for d in extra_dates if d}
    for f in find_dates(text):
        if not any(a.startswith(f.iso) or f.iso.startswith(a) for a in allowed_iso if a):
            return seqs, f"Datum {de(f.iso)} nicht in den Belegen"
    return seqs, None


def _sentence(text: str, refs: list[str], by_ref: dict, warnings: list,
              accident: str | None = None) -> str:
    seqs, problem = _validate(text, refs, by_ref, (accident or "",))
    t = text.strip()
    if problem:
        warnings.append(f"{problem}: „{t[:80]}“")
        return f"{WARN} {t} {_bl(seqs)} [{problem} — prüfen]".replace("  ", " ")
    return f"{t} {_bl(seqs)}"


# ------------------------------------------------------------------ section builders

def build_narrative(conn, case_id, llm, section, categories, warnings) -> str:
    entries = _entries(conn, case_id, categories)
    if not entries:
        return "[Keine belegten Einträge — Aktenauszug im Reiter „Register“ erstellen]"
    by_ref = {e["ref"]: e for e in entries}
    paras = []
    for i in range(0, len(entries), CHUNK_ENTRIES):
        chunk = entries[i:i + CHUNK_ENTRIES]
        out = call_llm(conn, case_id, llm, stage="draft_narrative", ref=f"{section} {i}",
                       prompt_version=NARRATIVE_VERSION,
                       prompt=NARRATIVE_PROMPT.format(section=section,
                                                      entries=_render_entries(chunk)),
                       schema=NARRATIVE_SCHEMA, max_tokens=6144)
        paras.append(" ".join(_sentence(s["text"], s.get("refs", []), by_ref, warnings)
                              for s in out.get("sentences", [])))
    return "\n\n".join(p for p in paras if p)


GROUP_TITLE = {"fuer_unfall": "Für einen Zusammenhang mit dem Ereignis spricht",
               "fuer_vorzustand": "Für einen Vorzustand / eine andere Ursache spricht",
               "offen": "Offen / unklar"}


def build_basis(conn, case_id, llm, topic, accident, warnings, ref_label) -> str:
    entries = _entries(conn, case_id, medical_only=True)
    if not entries:
        return f"[Keine belegten Einträge]\n\n{EXPERT_JUDGEMENT}"
    by_ref = {e["ref"]: e for e in entries}
    out = call_llm(conn, case_id, llm, stage="draft_basis", ref=ref_label,
                   prompt_version=BASIS_VERSION,
                   prompt=BASIS_PROMPT.format(topic=topic, accident_date=de(accident),
                                              entries=_render_entries(entries[:120])),
                   schema=BASIS_SCHEMA, max_tokens=4096)
    groups: dict[str, list[str]] = {k: [] for k in GROUP_TITLE}
    for p in out.get("points", []):
        group = p.get("group")
        if group not in groups:
            continue
        if NON_MEDICAL_ARG.search(p.get("text") or ""):
            warnings.append(f"verworfen (Rechts-/Versicherungsargument): „{p['text'][:80]}“")
            continue
        cited = [by_ref[r] for r in p.get("refs", []) if r in by_ref]
        if (group == "fuer_unfall" and accident and cited
                and all(e["entry_date"] < accident and not accident.startswith(e["entry_date"])
                        for e in cited)):
            group = "fuer_vorzustand"  # documented before the event: cannot support it
        groups[group].append(_sentence(p["text"], p.get("refs", []), by_ref, warnings,
                                       accident))
    findings = [dict(r) for r in conn.execute(
        "SELECT claim, source_a, source_b, created_by FROM findings WHERE case_id=? "
        "AND status='open'", (case_id,))]
    for f in findings:
        seqs = [s for s in (json.loads(x).get("global_seq") for x in (f["source_a"],
                                                                       f["source_b"]) if x)
                if s]
        label = "KI-Hinweis aus der Prüfung" if f["created_by"] == "ki" else \
            "Hinweis aus der Prüfung"
        groups["offen"].append(f"{label}: {f['claim']} {_bl(seqs)}")
    lines = ["*Entscheidungsgrundlage aus der Akte — keine Beurteilung.*", ""]
    for k, title in GROUP_TITLE.items():
        if groups[k]:
            lines.append(f"**{title}:**")
            lines += [f"- {x}" for x in groups[k]]
            lines.append("")
    lines.append(EXPERT_JUDGEMENT)
    return "\n".join(lines)


def build_questions(conn, case, llm, warnings, tpl: str = "allgemein") -> str:
    """Standard questions of the assignment type (structured answers from the expert)
    followed by the case-specific questions, each with its decision basis."""
    parts = []
    if tpl in ("iv", "uv", "at"):
        std = rs.build_standard_questions(case, tpl)
        if std:
            parts.append(std)
    qs = [dict(r) for r in conn.execute(
        "SELECT * FROM questions WHERE case_id=? ORDER BY ord", (case["id"],))]
    # The decision basis is built once in the Beurteilung section; repeating it per
    # question made half of the first real report redundant.
    basis_ziff = next((t.split(".", 1)[0] for k, t, _ in rs.TEMPLATES[tpl]
                       if k == "beurteilung"), None)
    if qs:
        parts.append("### Fallspezifische Fragen")
    elif tpl == "allgemein":
        parts.append("[Keine Beweisfragen erfasst — im Reiter „Übersicht“ eintragen oder aus dem "
                     "Gutachtenauftrag auslesen]")
    for q in qs:
        note = f"\n\n{ADEQUACY_NOTE}" if ADEQUACY.search(q["text"]) else ""
        if llm is None or basis_ziff:
            ref = (f"\n\n*Entscheidungsgrundlage aus der Akte: siehe Ziff. {basis_ziff}.*"
                   if basis_ziff else "")
            parts.append(f"**Frage {q['ord']}:** *{q['text']}*{ref}{note}\n\n"
                         "**Antwort:** [Ihre Antwort]")
            continue
        basis = build_basis(conn, case["id"], llm, f"Frage {q['ord']}: {q['text']}",
                            case.get("accident_date"), warnings, f"frage {q['ord']}")
        basis = basis.replace(EXPERT_JUDGEMENT, "**Antwort:** [Ihre Antwort]")
        parts.append(f"**Frage {q['ord']}:** *{q['text']}*{note}\n\n{basis}")
    return "\n\n".join(parts)


# ------------------------------------------------------------------ orchestration

def _upsert(conn, case_id, ord_, key, title, kind, content, warnings, llm_used, model_id):
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO draft_sections (case_id, ord, section_key, title, content_md, kind,
               status, warnings, prompt_version, model_id, generated_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
           ON CONFLICT(case_id, section_key) DO UPDATE SET
               ord=excluded.ord, title=excluded.title, content_md=excluded.content_md,
               kind=excluded.kind, status=excluded.status, warnings=excluded.warnings,
               prompt_version=excluded.prompt_version, model_id=excluded.model_id,
               generated_at=excluded.generated_at, updated_at=datetime('now')""",
        (case_id, ord_, key, title, content, kind,
         "empty" if kind == "manual" else "draft", json.dumps(warnings, ensure_ascii=False),
         {"narrative": NARRATIVE_VERSION, "basis": BASIS_VERSION,
          "questions": BASIS_VERSION}.get(kind) if llm_used else None,
         model_id if llm_used else None, now),
    )


LLM_KINDS = {"narrative", "basis"}
MANUAL_TEXT = {"dritte": "[Angaben von Dritten (auch behandelnde Ärzte) eintragen oder „keine“]"}


def generate_draft(conn: sqlite3.Connection, case_id: str, llm: JsonLLM | None,
                   keys: list[str] | None = None, progress=None) -> dict:
    """(Re)generate the sections of the template for this assignment type.

    Never overwritten: approved sections, sections the expert edited, and manual
    sections that already have content. Sections of a previous template (case type
    changed) are removed unless edited or approved."""
    case = dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())
    tpl = rs.template_for(case)
    sections = rs.TEMPLATES[tpl]
    wanted = {k for k, _, _ in sections}
    conn.execute(
        f"""DELETE FROM draft_sections WHERE case_id=? AND status!='approved'
            AND user_edited=0 AND section_key NOT IN ({",".join("?" * len(wanted))})""",
        (case_id, *wanted))
    existing = {r["section_key"]: dict(r) for r in conn.execute(
        "SELECT * FROM draft_sections WHERE case_id=?", (case_id,))}
    done, skipped, failed = [], [], []
    for ord_, (key, title, kind) in enumerate(sections, start=1):
        if keys and key not in keys:
            continue
        if progress:
            progress("Entwurf", ord_ - 1, len(sections))
        ex = existing.get(key)
        keep = ex and (ex["status"] == "approved" or ex["user_edited"]
                       or (kind == "manual" and ex["status"] != "empty"))
        if keep or (ex and kind in LLM_KINDS and llm is None):
            # content stays, but order and heading must follow the template — an
            # outdated heading would be a formal defect (EKQMB A1)
            if ex["ord"] != ord_ or ex["title"] != title:
                conn.execute("UPDATE draft_sections SET ord=?, title=? WHERE id=?",
                             (ord_, title, ex["id"]))
            skipped.append(key)
            continue
        if kind in LLM_KINDS and llm is None:
            skipped.append(key)
            continue
        warnings: list[str] = []
        try:
            if key == "ausgangslage":
                content = rs.build_ausgangslage(conn, case, tpl)
            elif key == "aktenauszug":
                content = rs.build_aktenauszug(conn, case_id)
            elif key == "befragung":
                from .interview import render_befragung

                iv = json.loads(case.get("interview_json") or "{}")
                content = (render_befragung(iv, iv.get("topics") or {}, tpl)
                           or rs.befragung_hint(tpl))
            elif key == "befund":
                content = rs.build_befund(conn, case)
            elif key in MANUAL_TEXT:
                content = MANUAL_TEXT[key]
            elif key == "med_beurteilung":
                content = rs.build_med_beurteilung(conn, case, tpl)
            elif key == "vm_beurteilung":
                content = rs.build_vm_beurteilung(conn, case)
            elif key == "beilagen":
                content = rs.build_beilagen(conn, case, tpl)
            elif key == "anamnese_aktenlage":
                content = build_narrative(conn, case_id, llm, title.split(". ", 1)[-1],
                                          None, warnings)
            elif key == "zusatzbefunde":
                content = build_narrative(conn, case_id, llm, title.split(". ", 1)[-1],
                                          {"diagnostik"}, warnings)
            elif key == "beurteilung":
                content = build_basis(conn, case_id, llm,
                                      "Beurteilung: Zusammenhang der Beschwerden mit dem Ereignis",
                                      case.get("accident_date"), warnings, "beurteilung")
            elif key == "fragen":
                content = build_questions(conn, case, llm, warnings, tpl)
            else:
                raise ValueError(f"unknown section {key}")
        except LlmError as e:
            failed.append(key)
            content, warnings = f"{WARN} Entwurf konnte nicht erstellt werden: {e}", [str(e)]
        content = swiss(content, tpl)
        llm_used = kind in LLM_KINDS or (key == "fragen" and llm is not None)
        _upsert(conn, case_id, ord_, key, title, kind, content, warnings,
                llm_used, llm.model_id if llm else None)
        done.append(key)
    database.audit(conn, case_id, "draft_generated",
                   f"Vorlage {tpl}: {len(done)} Abschnitte, {len(skipped)} unverändert, "
                   f"{len(failed)} Fehler")
    conn.commit()
    return {"template": tpl, "generated": done, "skipped": skipped, "failed": failed}


def reset_section(conn, case_id: str, key: str) -> None:
    """Discard manual edits so the next generation rebuilds the section from data."""
    conn.execute("UPDATE draft_sections SET user_edited=0, status='draft' WHERE case_id=? AND "
                 "section_key=? AND status!='approved'", (case_id, key))
    database.audit(conn, case_id, "section_reset", key, actor="user")
    conn.commit()


class ApprovalBlocked(ValueError):
    pass


def approval_problems(content: str) -> list[str]:
    probs = []
    if WARN in content:
        probs.append(f"{content.count(WARN)} markierte Stelle(n) ({WARN}) prüfen und bereinigen")
    if (ki := content.count("⟦KI⟧")):
        probs.append(f"{ki} KI-Vorschlag/-Vorschläge prüfen und übernehmen oder ändern")
    ph = PLACEHOLDER.findall(content)
    if ph:
        probs.append(f"Platzhalter ausfüllen: {', '.join(sorted(set(ph)))}")
    return probs


def update_section(conn, case_id: str, key: str, content: str | None = None,
                   status: str | None = None) -> dict:
    row = conn.execute("SELECT * FROM draft_sections WHERE case_id=? AND section_key=?",
                       (case_id, key)).fetchone()
    if not row:
        raise KeyError(key)
    content = row["content_md"] if content is None else content
    if status == "approved":
        if probs := approval_problems(content):
            raise ApprovalBlocked("; ".join(probs))
    new_status = status or ("draft" if row["status"] in ("empty", "approved") else row["status"])
    edited = int(bool(row["user_edited"]) or content != row["content_md"])
    conn.execute(
        """UPDATE draft_sections SET content_md=?, status=?, user_edited=?,
               updated_at=datetime('now'),
               approved_at=CASE WHEN ?='approved' THEN datetime('now') ELSE NULL END
           WHERE case_id=? AND section_key=?""",
        (content, new_status, edited, new_status, case_id, key))
    database.audit(conn, case_id, f"section_{new_status}", key, actor="user")
    conn.commit()
    return {"status": new_status}
