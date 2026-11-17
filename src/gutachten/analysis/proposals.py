# SPDX-License-Identifier: AGPL-3.0-or-later
"""KI-Vorentwurf: model proposals for the judgement placeholders of the draft.

Research use: one click from the Akte to a complete preliminary report. The tool
assists; the final judgement is always the expert's. Rules:
- Only judgement placeholders are filled (summary, consistency, therapy course,
  abilities, causality judgement, answers). Formal details, interview, examination
  findings, ICD codes and attachments are NEVER generated.
- Answers are concrete recommendations with reasons ("Empfehlung", "Begründung",
  "Zu prüfen"), not a retelling of the Akte. Questions that need the personal
  examination get a provisional recommendation from the records, explicitly marked
  as such, plus what the examination has to verify.
- Every proposal is wrapped in ⟦KI⟧…⟦/KI⟧ (highlighted in Word, "VORENTWURF" header)
  and blocks approval until the expert accepts or rewrites it.
- A sentence whose source or date cannot be verified is DROPPED (logged as a
  warning), not printed with ⚠. So are sentences arguing with insurer decisions or
  legal concepts, and sentences repeating an earlier one of the same section.
"""
from __future__ import annotations

import json
import re
import sqlite3

from ..dates import find_dates
from ..db import database
from ..llm.client import JsonLLM, LlmError
from . import report_sections as rs
from .common import call_llm
from .drafting import (
    NON_MEDICAL_ARG,
    WARN,
    _bl,
    _entries,
    _render_entries,
    _validate,
    de,
    swiss,
)

KI_OPEN, KI_CLOSE = "⟦KI⟧", "⟦/KI⟧"
PROPOSAL_VERSION = "vorentwurf-v3"
SECTIONS = ("med_beurteilung", "vm_beurteilung", "beurteilung", "fragen")
ANSWER_PH = r"\[Ihre Antwort\]"
CAUSALITY_PH = r"\[durch die/den Sachverständige/n zu formulieren\]"

# (placeholder, what to write, mode). mode "text": short assessment paragraph;
# mode "answer": recommendation + reasons + what to verify
FILLABLE: list[tuple[str, str, str]] = [
    (r"\[Zusammenfassung der persönlichen, beruflichen und gesundheitlichen Entwicklung "
     r"eintragen\]", "Zusammenfassung der bisherigen gesundheitlichen und beruflichen "
                     "Entwicklung", "text"),
    (r"\[Stellungnahme zu Konsistenz und Plausibilität[^\]]*\]",
     "Stellungnahme zu Konsistenz und Plausibilität der Befunde und Vorberichte "
     "einschliesslich Diskussion abweichender Einschätzungen", "text"),
    (r"\[Beurteilung des Therapieverlaufs[^\]]*\]",
     "Beurteilung des bisherigen Therapieverlaufs: angemessen und ausgeschöpft?, Prognose",
     "text"),
    (r"\[Funktions- und Fähigkeitsstörungen[^\]]*\]",
     "Funktions- und Fähigkeitsstörungen, Ressourcen und Belastungen", "text"),
    (CAUSALITY_PH, "ärztliche Beurteilung des Zusammenhangs mit dem Ereignis (natürliche "
                   "Kausalität, Vorzustand, Status quo sine)", "answer"),
    (ANSWER_PH, "Antwort auf die unmittelbar vorstehende Frage", "answer"),
]

# Questions only the personal examination can settle. They get a provisional
# recommendation from the records only (a model may otherwise state "Anwesenheit
# nicht möglich" as fact, from an acute finding two years earlier).
EXAM_DEPENDENT = re.compile(
    r"Stunden pro Tag|Einschränkung der Leistung|Arbeitsunfähigkeit insgesamt|"
    r"Verlauf der Entwicklung dieser Arbeitsfähigkeit|angepasste Tätigkeit aufweisen|"
    r"Integritätsschaden|namhafte Besserung|durch medizinische Massnahmen|"
    r"Behandlungsdauer|Belastbarkeit", re.I)

# Specific guidance for questions the model answered off-topic before
SPECIFIC: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Status quo", re.I),
     "Status quo ante = der Zustand unmittelbar vor dem Ereignis; status quo sine "
     "(eventu) = der Zustand, der sich durch den natürlichen Verlauf des Vorzustands "
     "auch ohne das Ereignis eingestellt hätte. Beide können nur NACH dem Ereignis "
     "erreicht werden, nie davor; ohne relevanten Vorzustand stellt sich die Frage nicht. "
     "Antworte genau eine Variante: (a) erreicht ab voraussichtlich <Zeitpunkt nach dem "
     "Ereignis> mit Begründung aus dem Vorzustand und dem Verlauf, (b) noch nicht "
     "erreicht, weil noch Unfallfolgen bestehen, oder (c) nicht beurteilbar. Widersprechen "
     "sich ärztliche Unterlagen dazu (z. B. Operateur gegen versicherungsinterne "
     "Aktenbeurteilung), ist die Antwort (c) mit beiden Positionen. Wiederhole NICHT die "
     "Kausalitätsbegründung."),
    (re.compile(r"Integritätsschaden", re.I),
     "Sage, ob nach Aktenlage voraussichtlich ein dauernder Integritätsschaden zu erwarten "
     "ist und welche medizinischen Kriterien (z. B. Arthrosegrad, Restfunktion, Instabilität) "
     "dafür massgeblich sind. KEINE Prozentzahl — die Bemessung erfordert die Untersuchung."),
    (re.compile(r"namhafte Besserung", re.I),
     "Sage, ob nach Aktenlage von weiterer Behandlung eine namhafte Besserung zu erwarten ist "
     "(z. B. ausstehende Operation, Rehabilitation) und was dafür bzw. dagegen spricht."),
    (re.compile(r"angepasste Tätigkeit aufweisen", re.I),
     "Beschreibe das Belastungsprofil einer angepassten Tätigkeit (Positionen, Gehen/Stehen, "
     "Knien, Heben, Leitern), soweit es aus den dokumentierten Diagnosen folgt."),
]

# Absolute prognoses or causal certainty cannot be derived from records alone
# ("irreversibel", "keine namhafte Besserung mehr", "hat … verursacht", "keine
# vollständige Wiederherstellung").
ABSOLUTE = re.compile(
    r"irreversib|unumkehrbar|nicht reversibel|keine (?:namhafte |wesentliche )?besserung mehr|"
    r"\bnie(?:mals)?\b|\bdauerhafte?[nrsm]?\b|endgültig|ausgeschlossen, dass|"
    r"(?:keine|nicht) (?:mehr )?(?:zu einer )?vollständige[nr]? (?:wiederherstellung|heilung)|"
    r"\b(?:hat|haben) (?:den|die|das) [^.]{0,60}verursacht", re.I)
# Internal entry ids must never reach the report
INTERNAL_REF = re.compile(r"\s*\(?\bE\d+(?:\s*(?:,|und|–|-)\s*E\d+)*\)?")


# Model artefacts: the "refs" field name echoed into the text ("… refs.", "(refs: …")
# by Gemma, empty reference brackets "[]" by other models.
REFS_ECHO = re.compile(r"\s*[(\[]?\s*\brefs?\b\s*:?(?:\s*\[[^\]]*\])?[\s,;]*[)\]]?(?=[\s.,;]|$)",
                       re.I)
EMPTY_BRACKETS = re.compile(r"\s*\[[\s,;]*\]")
EMPTY_PARENS = re.compile(r"\s*\([\s,;]*\)")


def _clean(t: str) -> str:
    t = INTERNAL_REF.sub("", t)
    t = EMPTY_PARENS.sub("", EMPTY_BRACKETS.sub("", REFS_ECHO.sub("", t)))
    return re.sub(r"\s+([.,;])", r"\1", re.sub(r"\s{2,}", " ", t)).strip()


TEXT_PROMPT = """\\
Du erstellst einen VORSCHLAG für ein orthopädisches Gutachten (Vorentwurf). Die
Letztbeurteilung trifft die/der Sachverständige; dein Vorschlag soll sie/ihn konkret
unterstützen. Abschnitt: {section}
Zu formulieren: {what}

Text unmittelbar davor im Gutachten:
<<<
{context}
>>>
Unfall-/Ereignisdatum: {accident}

Regeln:
- Ausschliesslich aus den belegten Einträgen und Hinweisen unten. Jeder Satz nennt in
  "refs" die Einträge (E…), auf die er sich stützt. Daten nur genau so, wie sie in den
  zitierten Einträgen stehen.
- Schlussfolgerungen statt Nacherzählung: der Aktenauszug steht bereits im Gutachten.
- Es hat KEINE persönliche Untersuchung stattgefunden: keine Untersuchungsbefunde erfinden.
- Entscheide oder Formulierungen des Versicherers (Verfügung, Leistungen, Sistierung,
  Vermutung, Gegenbeweis, Listendiagnose) sind keine medizinischen Argumente.
- Beweismass: überwiegende Wahrscheinlichkeit. Keine Rechtsbegriffe (Adäquanz,
  Invalidität, Erwerbsunfähigkeit). Schweizer Rechtschreibung (ss statt ß).
- Keine absoluten Prognosen ohne Untersuchung; Kausalität als "überwiegend
  wahrscheinlich". Keine Eintragsnummern (E1 …) im Text.
- Kurz und sachlich, höchstens 6 Sätze.

Belegte medizinische Einträge:
{entries}

Hinweise aus der Aktenprüfung:
{findings}
"""

ANSWER_PROMPT = """\\
Du formulierst einen begründeten VORSCHLAG für die Antwort der/des Sachverständigen in
einem orthopädischen Gutachten. Die Letztbeurteilung trifft die/der Sachverständige —
gib trotzdem eine KONKRETE fachliche Empfehlung mit Begründung, keine Aufzählung der Akte.

Frage (mit Überschrift):
<<<
{context}
>>>
Unfall-/Ereignisdatum: {accident}
{special}
Bereits beantwortete Fragen (NICHT wiederholen — die Empfehlung muss eine andere Frage
beantworten):
{previous}

Beantworte AUSSCHLIESSLICH die letzte Frage im Block oben.

Regeln:
- "empfehlung": 1–2 Sätze, die genau diese Frage beantworten (z. B. "Der Meniskusriss
  ist überwiegend wahrscheinlich natürlich kausal auf das Ereignis zurückzuführen.").
- "begruendung": höchstens 4 Sätze medizinischer Schlussfolgerung (warum), jeder mit
  "refs" auf die Einträge. Befunde nur stichwortartig benennen, nicht nacherzählen —
  der Aktenauszug steht bereits im Gutachten.
- "gelegenheitsursache": nur bei Kausalitätsfragen mit dokumentiertem Vorzustand, sonst
  leere Listen. "fuer_vorzustand" = Befunde, die zeigen, dass der Schaden im Vorzustand
  angelegt war und eine alltägliche Belastung ihn etwa zur selben Zeit ausgelöst hätte
  (z. B. lange bestehende degenerative Veränderungen, keine frischen Trauma-Zeichen,
  beschwerdefreies Intervall). "fuer_ereignis" = Befunde, die für das Ereignis als
  wesentliche Ursache sprechen (Schwere des Ereignisses, sofortige Symptome, frische
  Trauma-Zeichen). Ein Befund gehört nur auf die Seite, die er tatsächlich stützt.
  Jeder Punkt mit refs. Die Empfehlung muss aus dieser Abwägung folgen.
- "zu_pruefen": höchstens 3 kurze Punkte, die die persönliche Untersuchung oder weitere
  Unterlagen klären müssen.
- {exam_rule}
- Medizinische Argumente nur aus medizinischen Unterlagen. Entscheide oder Formulierungen
  des Versicherers (Verfügung, Leistungen, Sistierung, Vermutung, Gegenbeweis,
  Listendiagnose) sind KEINE Argumente. Nur natürliche Kausalität; keine Rechtsbegriffe
  (Adäquanz, Invalidität, Erwerbsunfähigkeit).
- Beweismass: überwiegende Wahrscheinlichkeit — Kausalität immer als "überwiegend
  wahrscheinlich" formulieren, nie als Gewissheit ("hat verursacht"). Ist ein Vorzustand
  dokumentiert, den möglichen Mitursachenanteil ausdrücklich nennen.
- Keine absoluten Prognosen ohne Untersuchung (irreversibel, keine Besserung mehr,
  dauerhaft, vollständige Wiederherstellung ausgeschlossen); stattdessen "derzeit nicht
  abschliessend beurteilbar" mit dem, was dafür zu klären ist.
- Arbeitsfähigkeit nicht pauschal: konkret nennen, welche Belastungen (z. B. Rotation,
  tiefes Knien, Treppen, Heben) eingeschränkt sind.
- Bei erheblichem Vorzustand prüfe medizinisch, ob eine alltägliche Belastung etwa zur
  selben Zeit denselben Schaden hätte auslösen können (Gelegenheitsursache). Ein
  Ereignis, das nur "Auslöser" auf vorgeschädigtem Boden war, begründet für sich keine
  überwiegende Wahrscheinlichkeit; nenne, was für und was gegen eine Gelegenheitsursache
  spricht (Schwere des Ereignisses, sofortige Symptome, frische Trauma-Zeichen).
- Widersprechen sich ärztliche Unterlagen (z. B. Operateur gegen beratenden Arzt der
  Versicherung), nenne beide Positionen mit Fundstelle und gewichte sie offen;
  übernimm nie ungeprüft die Einschätzung eines beratenden/versicherungsinternen Arztes.
- Widersprich keiner bereits gegebenen Empfehlung (Liste oben), auch nicht der
  ärztlichen Beurteilung in Ziff. 6/7. Nenne in den Texten
  keine Eintragsnummern (E1 …) — Fundstellen werden automatisch ergänzt.
- Daten nur genau so, wie sie in den zitierten Einträgen stehen. Schweizer
  Rechtschreibung (ss statt ß).

Belegte medizinische Einträge:
{entries}

Hinweise aus der Aktenprüfung:
{findings}
"""
EXAM_RULE_NORMAL = ("Es hat keine persönliche Untersuchung stattgefunden: keine "
                    "Untersuchungsbefunde erfinden.")
EXAM_RULE_PROVISIONAL = (
    "Diese Frage erfordert die persönliche Untersuchung. Gib eine VORLÄUFIGE Empfehlung "
    "nach Aktenlage, gestützt auf den jüngsten dokumentierten Zustand (Datum nennen), "
    "und nenne in \"zu_pruefen\" die Untersuchungsbefunde, die sie bestätigen oder "
    "widerlegen. Keine Untersuchungsbefunde erfinden.")
PROVISIONAL = "Vorläufig nach Aktenlage, vorbehaltlich der persönlichen Untersuchung:"

_SENT = {"type": "object",
         "properties": {"text": {"type": "string", "maxLength": 400},
                        "refs": {"type": "array", "items": {"type": "string"}, "maxItems": 6}},
         "required": ["text", "refs"], "additionalProperties": False}
TEXT_SCHEMA = {
    "type": "object",
    "properties": {"sentences": {"type": "array", "maxItems": 6, "items": _SENT}},
    "required": ["sentences"], "additionalProperties": False,
}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "empfehlung": _SENT,
        "begruendung": {"type": "array", "maxItems": 4, "items": _SENT},
        "zu_pruefen": {"type": "array", "maxItems": 3,
                       "items": {"type": "string", "maxLength": 200}},
        "gelegenheitsursache": {
            "type": "object",
            "properties": {"fuer_vorzustand": {"type": "array", "maxItems": 3, "items": _SENT},
                           "fuer_ereignis": {"type": "array", "maxItems": 3, "items": _SENT}},
            "required": ["fuer_vorzustand", "fuer_ereignis"], "additionalProperties": False},
    },
    "required": ["empfehlung", "begruendung", "zu_pruefen", "gelegenheitsursache"],
    "additionalProperties": False,
}


def _numbers(t: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)*", t))


def _tokens(t: str) -> set[str]:
    return {w for w in re.findall(r"\w+", t.lower()) if len(w) > 3}


def _repeats(t: str, seen: list[set[str]]) -> bool:
    """Same content as an earlier sentence of the section (also when reworded)."""
    tok = _tokens(t)
    return bool(tok) and any(len(tok & s) / len(tok) >= 0.6 for s in seen)


def _accept(s: dict, by_ref: dict, warnings: list, context: str, accident: str | None,
            seen: list[set[str]] | None) -> str | None:
    """One sentence -> rendered text with Bl. reference, or None if dropped."""
    t = _clean(s.get("text") or "")
    if not t:
        return None
    if ABSOLUTE.search(t):
        warnings.append(f"verworfen (absolute Aussage ohne Untersuchung): „{t[:80]}“")
        return None
    if NON_MEDICAL_ARG.search(t):
        warnings.append(f"verworfen (Rechts-/Versicherungsargument): „{t[:80]}“")
        return None
    if seen is not None:
        if _repeats(t, seen):
            return None
        seen.append(_tokens(t))
    refs = s.get("refs") or []
    # without source a sentence may only state what is open; its numbers must come
    # from the question itself (e.g. "100 %")
    if not refs and _numbers(t) <= _numbers(context):
        return t
    seqs, problem = _validate(t, refs, by_ref, (accident or "",))
    if problem:
        warnings.append(f"verworfen ({problem}): „{t[:80]}“")
        return None
    return f"{t} {_bl(seqs)}"


def _before_event(text: str, accident: str | None) -> bool:
    """A status quo "reached" at a date before the event (or "vor dem Unfall") is
    impossible by definition."""
    if not accident or not re.search(r"\berreicht", text, re.I):
        return False
    if re.search(r"(?:bereits )?vor dem (?:Unfall|Ereignis)[^.]{0,40}erreicht|erreicht[^.]{0,"
                 r"40}vor dem (?:Unfall|Ereignis)", text, re.I):
        return True
    # "erreicht ab/per <Datum vor dem Ereignis>"
    return any(f.iso[:10] < accident[:10] and
               re.search(r"\b(?:ab|per|am|seit)\b(?:\s+[\wäöü]+){0,2}\s*$",
                         text[max(0, f.start - 40):f.start], re.I)
               for f in find_dates(text) if len(f.iso) >= 10)


CAUSAL_QUESTION = re.compile(r"kausal|Zusammenhang|Ärztliche Beurteilung|Ursache|zuzurechnen|"
                             r"unfallbedingt", re.I)
TRIGGER = re.compile(r"auslös|verschlimmerungsmoment|(?:abgenützt|vorgeschädigt|abgenutzt)"
                     r"\w* Boden|bei bekannte[rm] \w+", re.I)
CLAIMS_CAUSAL = re.compile(r"überwiegend(?:er)? wahrscheinlich(?:keit)?(?![^.]{0,30}\bnicht\b)"
                           r"[^.]{0,80}(?:kausal|zurückzuführen|verursacht|bewirkt)", re.I)
NOT_CAUSAL = re.compile(r"\bnicht\b[^.]{0,40}(?:kausal|zurückzuführen|verursacht)|"
                        r"(?:kausal|zurückzuführen)[^.]{0,20}\bnicht\b|"
                        r"überwiegend wahrscheinlich (?:eine )?Gelegenheitsursache", re.I)


_DATE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")


def _no_dates(text: str) -> str:
    """Dates contain dots; the sentence patterns must not stop at them."""
    return _DATE.sub("DATUM", text)


def _polarity(text: str) -> int:
    """+1 causal, -1 not causal / occasional cause, 0 open (for consistency checks)."""
    t = _no_dates(text)
    if NOT_CAUSAL.search(t):
        return -1
    return 1 if CLAIMS_CAUSAL.search(t) else 0


OCCASIONAL_CHECK = ("Gelegenheitsursache: hätte eine alltägliche Belastung etwa zur selben "
                    "Zeit denselben Schaden auslösen können?")


def _answer_problem(out: dict, emp: str, same: str | None, context: str,
                    accident: str | None, by_ref: dict, qline: str) -> tuple[str | None, str]:
    """-> (problem, retry instruction) for a model recommendation, or (None, "")."""
    if "status quo" in context.lower() and _before_event(emp, accident):
        return "Status quo vor dem Ereignis", (
            "ACHTUNG: Der Status quo sine/ante kann nur NACH dem Ereignis "
            f"({de(accident)}) erreicht werden, nie davor.\n")
    if same:  # a model tends to copy the causality answer into other questions
        return "Empfehlung wiederholte frühere Antwort", (
            f"ACHTUNG: Deine Empfehlung wiederholte die Antwort zu „{same}“. Beantworte "
            f"AUSSCHLIESSLICH die Frage „{qline}“.\n")
    if ABSOLUTE.search(emp):
        return "Empfehlung zu absolut", (
            "ACHTUNG: Deine Empfehlung war zu absolut. Formuliere vorläufig, im Beweismass "
            "der überwiegenden Wahrscheinlichkeit, ohne endgültige Prognose.\n")
    if CAUSAL_QUESTION.search(context) and _polarity(emp) == 1 and TRIGGER.search(
            emp + " " + " ".join((b.get("text") or "") for b in out.get("begruendung") or [])):
        occ = out.get("gelegenheitsursache") or {}
        # both sides must be weighed — and survive the source check (a side whose points
        # all lack a valid source showed up as "nichts Belegtes")
        sides = [[x for x in occ.get(k) or []
                  if _accept(x, by_ref, [], context, accident, None)]
                 for k in ("fuer_vorzustand", "fuer_ereignis")]
        if not all(sides):
            # "Auslöser auf vorgeschädigtem Boden" must not be taken as causality
            return "Gelegenheitsursache nicht geprüft", (
                "ACHTUNG: Ein Ereignis, das nur Auslöser auf vorgeschädigtem Boden war, "
                "begründet allein keine überwiegende Wahrscheinlichkeit. Fülle "
                "'gelegenheitsursache' (was spricht für den Vorzustand, was für das Ereignis: "
                "Schwere des Ereignisses, sofortige Symptome, frische Trauma-Zeichen) und "
                "leite die "
                "Empfehlung daraus ab: Unfall überwiegend wahrscheinlich wesentliche Ursache / "
                "überwiegend wahrscheinlich Gelegenheitsursache / nicht abschliessend "
                "beurteilbar.\n")
    probe: list[str] = []
    if not _accept(out.get("empfehlung") or {}, by_ref, probe, context, accident, None):
        reason = probe[0] if probe else "leer"
        return "Empfehlung verworfen", (
            f"ACHTUNG: Deine Empfehlung wurde verworfen ({reason[:120]}). Nenne nur Daten, "
            "die wörtlich in den zitierten Einträgen stehen, und gib refs an.\n")
    return None, ""


def _render(sentences: list[dict], by_ref: dict, warnings: list, context: str = "",
            accident: str | None = None, seen: list[set[str]] | None = None) -> str:
    out = [r for s in sentences
           if (r := _accept(s, by_ref, warnings, context, accident, seen))]
    return " ".join(out)


def _render_answer(out: dict, by_ref: dict, warnings: list, context: str,
                   accident: str | None, seen: list[set[str]], provisional: bool) -> str:
    emp = _accept(out.get("empfehlung") or {}, by_ref, warnings, context, accident, None)
    if not emp:
        return ""
    if provisional and not emp.lower().startswith("vorläufig"):
        emp = f"{PROVISIONAL} {emp}"
    parts = [f"Empfehlung: {emp}"]
    why = _render(out.get("begruendung") or [], by_ref, warnings, context, accident, seen)
    if why:
        parts.append(f"Begründung: {why}")
    # the weighing belongs to causality questions only (Gemma also filled it for work
    # capacity questions)
    occ = (out.get("gelegenheitsursache") or {}) if CAUSAL_QUESTION.search(context) else {}
    pre = _render(occ.get("fuer_vorzustand") or [], by_ref, warnings, context, accident, None)
    evt = _render(occ.get("fuer_ereignis") or [], by_ref, warnings, context, accident, None)
    if pre or evt:
        parts.append("Abwägung Gelegenheitsursache — für den Vorzustand spricht: "
                     + (pre or "nichts Belegtes.") + " Für das Ereignis als wesentliche "
                     "Ursache spricht: " + (evt or "nichts Belegtes."))
    check = [_clean(c).rstrip(".") for c in out.get("zu_pruefen") or []
             if c.strip() and not NON_MEDICAL_ARG.search(c)
             and not re.search(r"\d{1,2}\.\d{1,2}\.\d{2,4}", c)]
    if check:
        parts.append("Zu prüfen: " + "; ".join(check) + ".")
    return " ".join(parts)


KI_BLOCK = re.compile(r"⟦KI⟧.*?⟦/KI⟧", re.S)


def _question_context(before: str) -> str:
    """What the placeholder answers: the nearest heading or question lines above it —
    without earlier proposals (the model otherwise copies its previous answer)."""
    lines = [ln for ln in KI_BLOCK.sub("", before).split("\n") if ln.strip()]
    picked: list[str] = []
    for ln in reversed(lines[-12:]):
        picked.insert(0, ln)
        if ln.startswith(("**", "### ")) and len(picked) > 1:
            break
    return "\n".join(picked)[-600:]


def _question_line(context: str) -> str:
    qs = [ln for ln in context.split("\n") if ln.startswith("*")]
    return (qs[-1] if qs else context.split("\n")[-1]).strip("* ")[:160]


def fill_section(conn, case: dict, llm: JsonLLM, row: dict, entries: list[dict],
                 findings_text: str, memory: dict | None = None, tick=None
                 ) -> tuple[str, int, list[str]]:
    """memory: recommendations given so far in the whole case (Ziff. 6/7 and the
    answers must not contradict each other)."""
    content = row["content_md"]
    tpl = rs.template_for(case)
    accident = case.get("accident_date")
    by_ref = {e["ref"]: e for e in entries}
    rendered_entries = _render_entries(entries[:120])
    warnings: list[str] = []
    memory = memory if memory is not None else {}
    seen: list[set[str]] = []
    previous: list[str] = memory.setdefault("previous", [])
    emp_seen: list[tuple[str, set[str]]] = memory.setdefault("emp_seen", [])
    filled = 0
    for pattern, what, mode in FILLABLE:
        while (m := re.search(pattern, content)):
            context = _question_context(content[:m.start()])
            try:
                if mode == "text":
                    out = call_llm(conn, case["id"], llm, stage="vorentwurf",
                                   ref=f"{row['section_key']}:{what[:30]}",
                                   prompt_version=PROPOSAL_VERSION,
                                   prompt=TEXT_PROMPT.format(
                                       section=row["title"], what=what, context=context,
                                       accident=accident or "unbekannt",
                                       entries=rendered_entries,
                                       findings=findings_text or "keine"),
                                   schema=TEXT_SCHEMA, max_tokens=1536)
                    text = _render(out.get("sentences", []), by_ref, warnings, context,
                                   accident, seen) or "Aus der Akte nicht ableitbar."
                else:
                    provisional = pattern == ANSWER_PH and bool(EXAM_DEPENDENT.search(context))
                    special = next((g for rx, g in SPECIFIC if rx.search(context)), "")
                    qline = _question_line(context)
                    retry, out_ref, same, problem = "", "", None, None
                    for _attempt in range(3):
                        out = call_llm(
                            conn, case["id"], llm, stage="vorentwurf_antwort",
                            ref=f"{row['section_key']}:{qline[:40]}",
                            prompt_version=PROPOSAL_VERSION,
                            prompt=ANSWER_PROMPT.format(
                                context=context, accident=accident or "unbekannt",
                                special=(f"Besonders: {special}\n" if special else "") + retry,
                                previous="\n".join(previous[-8:]) or "keine",
                                exam_rule=(EXAM_RULE_PROVISIONAL if provisional
                                           else EXAM_RULE_NORMAL),
                                entries=rendered_entries,
                                findings=findings_text or "keine"),
                            schema=ANSWER_SCHEMA, max_tokens=2048)
                        emp = _clean((out.get("empfehlung") or {}).get("text") or "")
                        same = next((q for q, tok in emp_seen if _repeats(emp, [tok])), None)
                        problem, retry = _answer_problem(out, emp, same, context, accident,
                                                         by_ref, qline)
                        if not problem:
                            break
                        warnings.append(f"{problem}: „{emp[:60]}“")
                    else:
                        if same:  # same question in other words: point to that answer
                            out, out_ref = {}, f"Siehe Empfehlung zu „{same}“ (oben)."
                        elif problem == "Gelegenheitsursache nicht geprüft":
                            # keep the (valid) text, but make the open point explicit
                            out = dict(out, zu_pruefen=[OCCASIONAL_CHECK]
                                       + list(out.get("zu_pruefen") or [])[:2])
                        elif problem == "Status quo vor dem Ereignis":
                            out = {}
                        # other problems: the validation below drops what stays unsupported
                    emp_seen.append((qline, _tokens(emp)))
                    text = _render_answer(out, by_ref, warnings, context, accident, seen,
                                          provisional) if out else out_ref
                    # only the causality questions themselves (not e.g. "Status quo" under
                    # the heading "Natürliche Kausalität")
                    pol = _polarity(emp) if text and CAUSAL_QUESTION.search(qline) else 0
                    if pol:
                        first = memory.setdefault("causal", (qline, pol))
                        if first[1] != pol:
                            # e.g. Ziff. 7 "kausal" vs. answer "nicht kausal".
                            # Neither side is forced — the expert decides, approval blocked.
                            warnings.append(f"Widerspruch zur Kausalitäts-Empfehlung zu "
                                            f"„{first[0]}“")
                            text = (f"{WARN} Widerspricht der Kausalitäts-Empfehlung zu "
                                    f"„{first[0]}“ — bitte entscheiden. {text}")
                    if text:
                        previous.append(f"- {_question_line(context)}: "
                                        f"{text.split(' Begründung:')[0][:200]}")
                    else:
                        text = ("Keine belastbare Empfehlung aus der Akte ableitbar — "
                                "Beurteilung durch die/den Sachverständige/n.")
            except LlmError as e:
                text = f"{WARN} Vorschlag fehlgeschlagen ({e})"
            text = swiss(text, tpl)
            content = content[:m.start()] + f"{KI_OPEN} {text} {KI_CLOSE}" + content[m.end():]
            filled += 1
            if tick:
                tick()
    return content, filled, warnings


def count_placeholders(text: str) -> int:
    return sum(len(re.findall(p, text)) for p, _, _ in FILLABLE)


def run_proposals(conn: sqlite3.Connection, case_id: str, llm: JsonLLM,
                  progress=None) -> dict:
    case = dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())
    entries = _entries(conn, case_id, medical_only=True)
    findings_text = "\n".join(
        f"- {r['claim']}" for r in conn.execute(
            "SELECT claim FROM findings WHERE case_id=? AND status!='rejected'", (case_id,)))
    total = 0
    memory: dict = {}
    todo = sum(count_placeholders(r[0]) for r in conn.execute(
        f"""SELECT content_md FROM draft_sections WHERE case_id=? AND status!='approved'
            AND user_edited=0 AND section_key IN ({",".join("?" * len(SECTIONS))})""",
        (case_id, *SECTIONS)))
    done = [0]

    def tick():
        done[0] += 1
        if progress:
            progress("KI-Vorentwurf", done[0], todo)
    for row in conn.execute(
            f"""SELECT * FROM draft_sections WHERE case_id=? AND status!='approved'
                AND user_edited=0 AND section_key IN ({",".join("?" * len(SECTIONS))})
                ORDER BY ord""", (case_id, *SECTIONS)).fetchall():
        row = dict(row)
        content, n, warnings = fill_section(conn, case, llm, row, entries, findings_text,
                                            memory, tick)
        dropped = [w for w in warnings if w.startswith("verworfen")]
        if dropped:  # traceable: what the model wrote and why it was not used
            database.audit(conn, case_id, "vorentwurf_verworfen",
                           f"{row['section_key']}: " + " | ".join(dropped))
        if content != row["content_md"]:
            old = json.loads(row["warnings"] or "[]")
            conn.execute("UPDATE draft_sections SET content_md=?, warnings=?, model_id=?, "
                         "prompt_version=?, updated_at=datetime('now') WHERE id=?",
                         (content, json.dumps(old + warnings, ensure_ascii=False),
                          llm.model_id, PROPOSAL_VERSION, row["id"]))
            total += n
        conn.commit()
    database.audit(conn, case_id, "vorentwurf", f"{total} KI-Vorschläge eingesetzt")
    conn.commit()
    return {"proposals": total}


def accept_proposals(conn, case_id: str, key: str) -> int:
    """The expert reviewed the proposals of a section: remove the markers, keep the
    text as their own (protected from regeneration)."""
    row = conn.execute("SELECT content_md FROM draft_sections WHERE case_id=? AND "
                       "section_key=?", (case_id, key)).fetchone()
    if not row:
        raise KeyError(key)
    n = row[0].count(KI_OPEN)
    text = row[0].replace(f"{KI_OPEN} ", "").replace(f" {KI_CLOSE}", "") \
        .replace(KI_OPEN, "").replace(KI_CLOSE, "")
    conn.execute("UPDATE draft_sections SET content_md=?, user_edited=1, status='reviewed', "
                 "updated_at=datetime('now') WHERE case_id=? AND section_key=?",
                 (text, case_id, key))
    database.audit(conn, case_id, "ki_proposals_accepted", f"{key}: {n}", actor="user")
    conn.commit()
    return n
