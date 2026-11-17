# SPDX-License-Identifier: AGPL-3.0-or-later
"""Language check of the draft — hints, never blocking.

Based on the EKQMB checklist (B2: technical terms and abbreviations explained for
non-medical readers; B3: insurance-medical terminology used correctly, no legal
conclusions) and the FMH/SAMW guide (experts answer factual, not legal questions;
causality to the standard of "überwiegende Wahrscheinlichkeit").
"""
from __future__ import annotations

import re

LEGAL_TERMS: list[tuple[str, str, str]] = [
    (r"\badäqua(?:nz|te[nrsm]?|t)\b", "Adäquanz / adäquate Kausalität",
     "Rechtsfrage — der Begriff darf in medizinischen Ausführungen nicht verwendet werden; "
     "nur zur natürlichen Kausalität Stellung nehmen."),
    (r"\binvalidität\b|\binvalid(?:e[nrsm]?)?\b", "Invalidität",
     "Rechtsbegriff — stattdessen Arbeitsfähigkeit bzw. Funktionseinschränkungen beschreiben."),
    (r"\berwerbsunfähig(?:keit)?\b|\berwerbseinbusse\b", "Erwerbsunfähigkeit",
     "Rechtsbegriff — medizinisch ist die Arbeitsfähigkeit zu beurteilen."),
    (r"\bverschulden\b", "Verschulden", "Rechtsfrage — nicht Gegenstand des Gutachtens."),
    (r"\brentenanspruch\b|\banspruch auf (?:eine )?rente\b", "Rentenanspruch",
     "Leistungsfrage des Versicherers — nicht medizinisch zu beantworten."),
    (r"\bintegritätsentschädigung\b", "Integritätsentschädigung",
     "Leistungsbegriff — medizinisch den Integritätsschaden (in %) beurteilen."),
    (r"\blistendiagnose\b|\blistenverletzung\b|vermutung de[rs] (?:unfall)?kausalität|"
     r"\bgegenbeweis\b", "Listenverletzung / Vermutung / Gegenbeweis (Art. 6 Abs. 2 UVG)",
     "Rechtliche Beweisregel des Versicherers — medizinisch nur beschreiben, ob die "
     "Verletzung überwiegend wahrscheinlich vorwiegend auf Abnützung oder Erkrankung "
     "zurückzuführen ist."),
    (r"\bsistier", "Sistierung von Leistungen",
     "Verwaltungsentscheid — kein medizinisches Argument."),
]

CAUSAL = re.compile(r"zusammenhang|kausal|unfallfolge|zurückzuführen|unfallbedingt", re.I)
WEAK = re.compile(r"\bmöglich(?:erweise)?\b|\bdenkbar\b|nicht (?:auszuschliessen|"
                  r"ausgeschlossen)|\bvermutlich\b|\beventuell\b", re.I)
STRONG = re.compile(r"überwiegend", re.I)

# understood by legal readers or explained elsewhere by convention
KNOWN_ABBR = {
    "AHV", "IV", "UV", "UVG", "IVG", "ATSG", "ATSV", "KSVI", "ICD", "BGE", "SIM", "FMH",
    "EKQMB", "SUVA", "MRI", "MRT", "CT", "EKG", "AF", "AUF", "CH", "AT", "GM", "ZPO", "DSG",
    "DSGVO", "KVG", "VVG", "ID", "PDF", "OK", "II", "III", "VI", "VII", "VIII", "KI",
}
ABBR = re.compile(r"\b[A-ZÄÖÜ]{2,6}\b")
ASSESSMENT_KEYS = {"med_beurteilung", "vm_beurteilung", "beurteilung", "fragen"}


SENTENCE_END = re.compile(
    r"(?<=[.!?])(?<!\b\w\.)(?<!\bca\.)(?<!\bDr\.)(?<!\bvgl\.)(?<!\bbzw\.)(?<!\bevtl\.)"
    r"(?<!\bggf\.)(?<!\bNr\.)(?<!\bSt\.)\s+|\n+")


def _sentences(text: str) -> list[str]:
    # no split after single-letter or common abbreviations ("d. A.", "z. B.", "bzw.")
    return [s.strip() for s in SENTENCE_END.split(text) if s.strip()]


def check_section(key: str, text: str, whole_report: str) -> list[dict]:
    text = text.replace("⟦KI⟧", "").replace("⟦/KI⟧", "")
    hints: list[dict] = []
    low = text.lower()
    for pattern, term, hint in LEGAL_TERMS:
        if re.search(pattern, low):
            hints.append({"kind": "rechtsbegriff", "text": term, "hint": hint})
    for s in _sentences(text):
        if CAUSAL.search(s) and WEAK.search(s) and not STRONG.search(s):
            hints.append({"kind": "beweismass", "text": s[:160],
                          "hint": "Beweismass ist die überwiegende Wahrscheinlichkeit — "
                                  "Aussage präzisieren („überwiegend wahrscheinlich“ / "
                                  "„möglich, aber nicht überwiegend wahrscheinlich“)."})
    if key in ASSESSMENT_KEYS:
        found = sorted({a for a in ABBR.findall(text) if a not in KNOWN_ABBR})
        explained = {a for a in found
                     if re.search(rf"\b{a}\s*\(|\(\s*{a}\s*\)", whole_report)}
        for a in found:
            if a not in explained:
                hints.append({"kind": "abkuerzung", "text": a,
                              "hint": "Abkürzung für nichtmedizinische Leser erklären, z. B. "
                                      f"„vorderes Kreuzband ({a})“ (EKQMB B2)."})
    return hints


def check_report(sections: list[dict]) -> dict[str, list[dict]]:
    whole = "\n".join(s["content_md"] for s in sections)
    return {s["section_key"]: check_section(s["section_key"], s["content_md"], whole)
            for s in sections}
