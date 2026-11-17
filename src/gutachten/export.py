# SPDX-License-Identifier: AGPL-3.0-or-later
"""Word export of the Gutachten (python-docx).

Layout in the manner of a legal / insurance-medicine expert opinion: black and
white, one classic serif (Times New Roman 12 pt), justified text with hyphenation,
numbered bold headings, tables with fine rules only, a cover page with the formal
details, "Seite x von y", place, date and signature at the end.

Typography: German quotation marks, en dash as Gedankenstrich and in ranges,
non-breaking spaces in "Bl. 4", "d. A.", "z. B.", "Art. 6", "12 %" and units.

Until every section is approved, every page says ENTWURF (or VORENTWURF when
unreviewed model proposals remain). Model proposals are shaded grey and labelled
"[KI-Vorschlag, ungeprüft]" — visible in a black-and-white print.
The export is written to cases/<id>/exports/ and audited.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import config
from .analysis.drafting import de
from .cases import connect_case
from .db import database

# Book Antiqua: the Palatino design (Hermann Zapf), shipped with Office on Windows and
# Mac — a classic book face; set slightly smaller than Times for the same colour.
FONT = "Book Antiqua"
SIZE = Pt(11)
SMALL = Pt(9)
TEXT_WIDTH = Cm(15.5)   # A4 minus 3.0 cm (binding) and 2.5 cm
BLACK = RGBColor(0, 0, 0)
KI_SHADE = "E6E6E6"  # light grey: visible in black-and-white print
KI_LABEL = "[KI-Vorschlag, ungeprüft] "

INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")
KI = re.compile(r"⟦KI⟧\s*(.*?)\s*⟦/KI⟧", re.S)
NBSP = " "

# Defaults per assignment type; the expert's own title (settings) takes precedence.
# CH: named after the specialty "Orthopädische Chirurgie und Traumatologie des
# Bewegungsapparates" (courts commission "orthopädisch-traumatologische Gutachten");
# the kind of assignment goes into a subtitle, not the title.
TITLE = {"iv": "Orthopädisch-traumatologisches Gutachten",
         "uv": "Orthopädisch-traumatologisches Gutachten",
         "allgemein": "Orthopädisch-traumatologisches Gutachten",
         "at": "Sachverständigengutachten aus dem Fachgebiet Orthopädie und Traumatologie"}
_COURT = re.compile(r"gericht", re.I)


def report_subtitle(tpl: str, case: dict) -> str | None:
    """The kind of assignment, below the title."""
    if tpl == "iv":
        return "Monodisziplinäres Gutachten gemäss Art. 44 ATSG"
    if tpl == "uv":
        return "Gutachten in der Unfallversicherung (UVG)"
    if tpl == "allgemein" and _COURT.search(case.get("auftraggeber") or ""):
        return "Gerichtsgutachten"
    return None


def report_title(tpl: str, expert: dict) -> str:
    return (expert.get("report_title") or "").strip() or TITLE.get(tpl,
                                                                 "Orthopädisches Gutachten")


# ------------------------------------------------------------------ typography

def typeset(text: str) -> str:
    """Classic German typography for running text (markdown markers untouched)."""
    t = text
    t = re.sub(r"\s+—\s+|\s+-\s+", " – ", t)                      # Gedankenstrich
    # ranges 3–5 and date ranges — but never Neutral-0 measurements (0-0-140, 20-0-30)
    neutral = re.findall(r"\d+-\d+-\d+", t)
    for k, v in enumerate(neutral):
        t = t.replace(v, f"\x00{k}\x00", 1)
    t = re.sub(r"(?<=\d)\s*[-—]\s*(?=\d)", "–", t)
    for k, v in enumerate(neutral):
        t = t.replace(f"\x00{k}\x00", v, 1)
    t = re.sub(r'"([^"\n]+)"', "„\\1“", t)                          # „…“
    t = t.replace("...", "…")
    abbr = [r"Bl\.", r"d\. A\.", r"z\. B\.", r"u\. a\.", r"d\. h\.", r"Art\.", r"Abs\.",
            r"lit\.", r"Ziff\.", r"Nr\.", r"S\.", r"E\.", r"Dr\.", r"med\.", r"Prof\.",
            r"ca\.", r"vgl\."]
    for a in abbr:
        t = re.sub(rf"(?<!\w)({a}) (?=\S)", lambda m: m.group(1) + NBSP, t)
    t = re.sub(r"\b(d\.)\s(A\.)", r"\1" + NBSP + r"\2", t)
    t = re.sub(r"\b(z\.)\s(B\.)", r"\1" + NBSP + r"\2", t)
    t = re.sub(r"(\d) (%|°|cm|mm|kg|ml|Tage?n?|Wochen|Monate?n?|Jahre?n?)\b",
               lambda m: m.group(1) + NBSP + m.group(2), t)
    t = re.sub(r"(\d) %", r"\1" + NBSP + "%", t)
    return t


# ------------------------------------------------------------------ low-level helpers

def _set_font(run, size=SIZE, bold=None, italic=None) -> None:
    run.font.name = FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    run.font.size = size
    run.font.color.rgb = BLACK
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def _shade(run, fill: str) -> None:
    rpr = run._element.get_or_add_rPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    rpr.append(shd)


def _field(par, instr: str) -> None:
    """PAGE / NUMPAGES field."""
    for kind, text in (("begin", None), (None, instr), ("separate", None), (None, "1"),
                       ("end", None)):
        run = par.add_run()
        _set_font(run, SMALL)
        if kind:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), kind)
            run._element.append(fc)
        elif text == instr:
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = f" {instr} "
            run._element.append(it)
        else:
            run.text = text


def _rules(table, outer: bool = True) -> None:
    """Fine black rules: top and bottom of the table, a rule under the header row."""
    tbl = table._tbl
    pr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "bottom", "insideH") if outer else ("insideH",):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "6" if edge != "insideH" else "2")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "000000")
        borders.append(el)
    for edge in ("left", "right", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    pr.append(borders)


def _no_borders(table) -> None:
    pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    pr.append(borders)


def _keep_with_next(par) -> None:
    par.paragraph_format.keep_with_next = True


def _tracking(rpr_owner, points: float) -> None:
    """Letter-spacing (small caps need a little air)."""
    rpr = rpr_owner.get_or_add_rPr() if hasattr(rpr_owner, "get_or_add_rPr") \
        else rpr_owner
    sp = OxmlElement("w:spacing")
    sp.set(qn("w:val"), str(int(points * 20)))
    rpr.append(sp)


def _rule(par, edge: str = "bottom", size: int = 4) -> None:
    """Hairline under (or above) a paragraph."""
    ppr = par._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    el = OxmlElement(f"w:{edge}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(size))
    el.set(qn("w:space"), "4")
    el.set(qn("w:color"), "000000")
    bdr.append(el)
    ppr.append(bdr)


def _caps(run, size, points: float = 0.6) -> None:
    _set_font(run, size)
    run.font.small_caps = True
    _tracking(run._element, points)


# ------------------------------------------------------------------ styles

def _styles(doc) -> None:
    st = doc.styles
    normal = st["Normal"]
    normal.font.name = FONT
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.font.size = SIZE
    normal.font.color.rgb = BLACK
    pf = normal.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.3
    pf.space_after = Pt(5)
    pf.widow_control = True
    for name, size, before, after, italic in (("Heading 1", Pt(11.5), 20, 7, False),
                                              ("Heading 2", Pt(11), 12, 3, True),
                                              ("Heading 3", Pt(11), 9, 2, True)):
        h = st[name]
        h.font.name = FONT
        h.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        h.element.rPr.rFonts.set(qn("w:ascii"), FONT)
        h.element.rPr.rFonts.set(qn("w:hAnsi"), FONT)
        h.font.size = size
        h.font.bold = False  # classic: small caps for main headings, italics below
        h.font.italic = italic
        if not italic:
            h.font.small_caps = True
            _tracking(h.element.get_or_add_rPr(), 0.6)
        h.font.color.rgb = BLACK
        h.paragraph_format.space_before = Pt(before)
        h.paragraph_format.space_after = Pt(after)
        h.paragraph_format.keep_with_next = True
        h.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for name in ("List Bullet", "List Number"):
        s = st[name]
        s.font.name = FONT
        s.font.size = SIZE
        s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        s.paragraph_format.space_after = Pt(3)
    # automatic hyphenation (German): justified text without rivers
    settings = doc.settings.element
    auto = OxmlElement("w:autoHyphenation")
    auto.set(qn("w:val"), "true")
    settings.append(auto)
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "de-CH")
    normal.element.get_or_add_rPr().append(lang)


def _page_setup(section) -> None:
    section.page_height, section.page_width = Cm(29.7), Cm(21.0)
    section.top_margin, section.bottom_margin = Cm(2.8), Cm(2.5)
    section.left_margin, section.right_margin = Cm(3.0), Cm(2.5)
    section.header_distance = section.footer_distance = Cm(1.3)


def _header_footer(section, running_title: str, status: str | None) -> None:
    section.different_first_page_header_footer = True
    hp = section.header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = hp.add_run(running_title)
    _caps(r, Pt(8.5), 0.5)
    if status:
        r = hp.add_run("\t" + status)
        _set_font(r, Pt(8.5), italic=True)
        hp.paragraph_format.tab_stops.add_tab_stop(TEXT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)
    fp = section.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("Seite ")
    _set_font(r, Pt(8.5))
    _field(fp, "PAGE")
    r = fp.add_run(" von ")
    _set_font(r, Pt(8.5))
    _field(fp, "NUMPAGES")
    # cover page: status only
    first = section.first_page_header.paragraphs[0]
    first.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if status:
        r = first.add_run(status)
        _set_font(r, Pt(8.5), italic=True)


# ------------------------------------------------------------------ text rendering

def _plain_runs(par, text: str, size=SIZE) -> list:
    runs = []
    for part in INLINE.split(typeset(text)):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            r = par.add_run(part[2:-2])
            _set_font(r, size, bold=False)  # sparing bold: only title and headings
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            r = par.add_run(part[1:-1])
            _set_font(r, size, italic=True)
        else:
            r = par.add_run(part)
            _set_font(r, size)
        runs.append(r)
    return runs


def _runs(par, text: str, size=SIZE) -> None:
    """Markdown-light runs; ⟦KI⟧…⟦/KI⟧ = unreviewed model proposal (grey, labelled)."""
    pos = 0
    for m in KI.finditer(text):
        _plain_runs(par, text[pos:m.start()], size)
        label = par.add_run(KI_LABEL)
        _set_font(label, SMALL, italic=True)
        _shade(label, KI_SHADE)
        for run in _plain_runs(par, m.group(1), size):
            _shade(run, KI_SHADE)
        pos = m.end()
    _plain_runs(par, text[pos:], size)


def _table(doc, rows: list[str]) -> None:
    """Markdown pipe table -> table with fine rules (header row bold)."""
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows
             if not re.fullmatch(r"\|?\s*(-{3,}\s*\|\s*)+-{0,}\s*\|?", r.strip())]
    if not cells:
        return
    t = doc.add_table(rows=0, cols=max(len(r) for r in cells))
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    _rules(t)
    for row in cells:
        out = t.add_row().cells
        for j, val in enumerate(row):
            p = out[j].paragraphs[0]
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_after = Pt(2)
            _runs(p, val, SMALL)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


COUNTRY_NOTE = re.compile(r"\s*·\s*Rechtsgebiet:\s*(?:Schweiz|Österreich|Deutschland|CH|AT|DE)")


def _markdown(doc, md: str) -> None:
    # the country is evident to client and court (older, already approved texts)
    md = COUNTRY_NOTE.sub("", md)
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            _table(doc, block)
            continue
        i += 1
        if not line:
            continue
        if line.startswith("### "):
            _runs(doc.add_paragraph(style="Heading 2"), line[4:])
        elif line.startswith("- "):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.75)
            p.paragraph_format.first_line_indent = Cm(-0.5)
            p.paragraph_format.tab_stops.add_tab_stop(Cm(0.75))
            p.paragraph_format.space_after = Pt(3)
            _runs(p, "–\t" + line[2:])
        elif re.match(r"^\d+\. ", line):
            # literal numbers: Word's list numbering would continue across lists
            num, rest = re.match(r"^(\d+\.) (.*)$", line).groups()
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.75)
            p.paragraph_format.first_line_indent = Cm(-0.75)
            p.paragraph_format.tab_stops.add_tab_stop(Cm(0.75))
            p.paragraph_format.space_after = Pt(3)
            _runs(p, f"{num}\t{rest}")
        elif re.fullmatch(r"\*\*[^*]+\*\*:?", line.strip()):
            p = doc.add_paragraph()               # run-in subheading: italic, not bold
            _runs(p, "*" + line.strip().replace("**", "") + "*")
            p.paragraph_format.space_before = Pt(8)
            _keep_with_next(p)
        elif re.fullmatch(r"\*[^*].*\*:?", line.strip()):
            p = doc.add_paragraph()               # question line (italic)
            _runs(p, line.strip())
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _keep_with_next(p)
        else:
            _runs(doc.add_paragraph(), line)


# ------------------------------------------------------------------ cover & signature

def _cover(doc, case: dict, tpl: str, final: bool, status: str | None,
           expert: dict) -> None:
    for _ in range(5):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(10)
    r = p.add_run(report_title(tpl, expert))
    _caps(r, Pt(17), 1.5)
    if sub := report_subtitle(tpl, case):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(10)
        r = p.add_run(sub)
        _set_font(r, SIZE)
    rule = doc.add_paragraph()           # short centred hairline under the title
    rule.paragraph_format.left_indent = rule.paragraph_format.right_indent = Cm(5.75)
    _rule(rule)
    if case.get("auftraggeber"):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(8)
        r = p.add_run(f"zuhanden {case['auftraggeber']}")
        _set_font(r, SIZE, italic=True)
    if status:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(status)
        _set_font(r, SMALL, italic=True)
    for _ in range(4):
        doc.add_paragraph()
    rows = [
        ("Versicherte Person", case.get("patient_name") or case.get("patient_ref")),
        ("Geburtsdatum", de(case.get("patient_dob")) if case.get("patient_dob") else None),
        ("Adresse", case.get("patient_address")),
        ("Sozialversicherungs-Nr.", case.get("ahv_nr")),
        ("Ereignis vom", de(case.get("accident_date")) if case.get("accident_date")
         else None),
        ("Auftrag vom", de(case.get("order_date")) if case.get("order_date") else None),
        ("Akten erhalten am", de(case.get("received_date")) if case.get("received_date")
         else None),
        ("Untersuchung am", de(case.get("exam_date")) if case.get("exam_date") else None),
        ("Dolmetscher/in", case.get("interpreter")),
        ("Gutachter/in", ", ".join(x for x in (expert.get("name"), expert.get("title"))
                                    if x) or None),
    ]
    rows = [(k, v) for k, v in rows if v]
    t = doc.add_table(rows=0, cols=2)
    _no_borders(t)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for _ in rows:
        t.add_row()
    for col, w in zip(t.columns, (Cm(5.0), Cm(9.0)), strict=True):
        col.width = w
    for (k, v), row in zip(rows, t.rows, strict=True):
        c = row.cells
        c[0].width, c[1].width = Cm(5.0), Cm(9.0)
        for cell, text, label in ((c[0], k, True), (c[1], str(v), False)):
            par = cell.paragraphs[0]
            par.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            par.paragraph_format.space_after = Pt(5)
            r = par.add_run(typeset(text))
            if label:
                _caps(r, Pt(9.5), 0.4)
            else:
                _set_font(r, SIZE)
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    place = (expert.get("address") or "").split("\n")[-1].strip()
    r = p.add_run(", ".join(x for x in (place, de(dt.date.today().isoformat())) if x))
    _set_font(r, SIZE)


def _signature(doc, expert: dict, final: bool) -> None:
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    place = (expert.get("address") or "").split("\n")[-1].strip()
    r = p.add_run(f"{place or 'Ort'}, {de(dt.date.today().isoformat())}")
    _set_font(r, SIZE)
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.right_indent = Cm(8.5)
    p.paragraph_format.space_after = Pt(0)
    _rule(p, "top")
    r = p.add_run(typeset(expert.get("name") or "Name der/des Sachverständigen"))
    _set_font(r, SIZE)
    if expert.get("title"):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run(typeset(expert["title"]))
        _set_font(r, SIZE)


# ------------------------------------------------------------------ export

def export_docx(case_id: str) -> tuple[Path, bool]:
    from .analysis import report_sections as rs

    conn = connect_case(case_id)
    try:
        case = dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())
        tpl = rs.template_for(case)
        keys = [k for k, _, _ in rs.TEMPLATES[tpl]]
        sections = sorted((dict(r) for r in conn.execute(
            "SELECT * FROM draft_sections WHERE case_id=?", (case_id,))
            if r["section_key"] in keys), key=lambda s: keys.index(s["section_key"]))
        docs = [dict(r) for r in conn.execute(
            "SELECT * FROM documents WHERE case_id=? AND excluded=0 ORDER BY start_seq",
            (case_id,))]
        final = bool(sections) and all(s["status"] == "approved" for s in sections)
        ki = any("⟦KI⟧" in s["content_md"] for s in sections)
        status = None if final else ("VORENTWURF – enthält ungeprüfte KI-Vorschläge" if ki
                                     else "ENTWURF – nicht freigegeben")
        expert = config.load_settings().get("expert") or {}

        doc = Document()
        _styles(doc)
        _page_setup(doc.sections[0])
        person = case.get("patient_name") or case.get("patient_ref") or ""
        running = report_title(tpl, expert) + (f" – {person}" if person else "")
        _header_footer(doc.sections[0], running, status)
        _cover(doc, case, tpl, final, status, expert)

        if not sections:
            doc.add_paragraph("Noch kein Entwurf erstellt.")
        for n, s in enumerate(sections):
            h = doc.add_paragraph(style="Heading 1")
            if n == 0:
                h.paragraph_format.page_break_before = True  # after the cover page
            _runs(h, s["title"])
            _markdown(doc, s["content_md"])

        if final:
            _signature(doc, expert, final)

        if docs:
            new = doc.add_section(WD_SECTION.NEW_PAGE)
            _page_setup(new)
            _runs(doc.add_paragraph(style="Heading 1"), "Fundstellenverzeichnis")
            p = doc.add_paragraph()
            _runs(p, "Die Verweise „Bl. … d. A.“ im Text beziehen sich auf die folgende "
                     "Paginierung der Akte.", SMALL)
            t = doc.add_table(rows=1, cols=3)
            _rules(t)
            for c, h in zip(t.rows[0].cells, ("Blatt", "Dokument", "Datum"), strict=True):
                r = c.paragraphs[0].add_run(h)
                _set_font(r, SMALL, italic=True)
            for d in docs:
                row = t.add_row().cells
                vals = (f"Bl. {d['start_seq']}" + (f"–{d['end_seq']}"
                                                   if d["end_seq"] != d["start_seq"] else ""),
                        d["title"] or "",
                        de(d.get("doc_date")) if d.get("doc_date") else "–")
                for c, v in zip(row, vals, strict=True):
                    c.paragraphs[0].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    r = c.paragraphs[0].add_run(typeset(v))
                    _set_font(r, SMALL)

        out_dir = config.case_dir(case_id) / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
        path = out_dir / f"Gutachten-{'final' if final else 'Entwurf'}-{stamp}.docx"
        doc.save(path)
        database.audit(conn, case_id, "export_docx", f"{path.name} (final={final})",
                       actor="user")
        conn.commit()
        return path, final
    finally:
        conn.close()
