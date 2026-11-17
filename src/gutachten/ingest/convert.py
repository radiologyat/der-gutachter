# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import modules for file types other than PDF and images.

Every module turns its file into a text PDF (A4, with a header naming the original
file). From there the normal pipeline applies: pages with a stable "Bl." number,
text layer instead of OCR, citations with highlighting. The original file is kept
unchanged in inbox/.

Supported: Word (.docx), RTF, plain text/Markdown, HTML, e-mail (.eml, attachments
are imported as files of their own). Audio and unknown formats get a placeholder page
("nicht lesbar — manuell zusammenfassen") so nothing in the folder silently
disappears.
"""
from __future__ import annotations

import email
import email.policy
import html
import re
from pathlib import Path

import pymupdf as fitz

DOCX = {".docx"}
RTF = {".rtf"}
TEXT = {".txt", ".md", ".csv"}
HTML = {".html", ".htm"}
EML = {".eml"}
AUDIO = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".wma"}
CONVERTIBLE = DOCX | RTF | TEXT | HTML | EML
# system files a copied folder often contains — skipped without a trace in the Akte
IGNORED = {"thumbs.db", "desktop.ini", ".ds_store"}

KIND_LABEL = {**dict.fromkeys(DOCX, "Word-Dokument"), **dict.fromkeys(RTF, "RTF-Dokument"),
              **dict.fromkeys(TEXT, "Textdatei"), **dict.fromkeys(HTML, "HTML-Dokument"),
              **dict.fromkeys(EML, "E-Mail"), **dict.fromkeys(AUDIO, "Audiodatei")}

CSS = ("body{font-family:sans-serif;font-size:10.5pt;line-height:1.35}"
       ".hdr{font-size:8.5pt;color:#555;border-bottom:1px solid #999;padding-bottom:4pt;"
       "margin-bottom:8pt}p{margin:0 0 5pt 0}.ph{font-size:12pt;color:#a00}")


def ignored(name: str) -> bool:
    return name.lower() in IGNORED or name.startswith("~$")


# ------------------------------------------------------------------ text extraction

def _docx_text(src: Path) -> str:
    from docx import Document

    d = Document(str(src))
    out: list[str] = []
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append("".join(t.text or "" for t in child.iter() if t.tag.endswith("}t")))
        elif tag == "tbl":
            for row in child.iter():
                if row.tag.endswith("}tr"):
                    cells = []
                    for cell in row:
                        if cell.tag.endswith("}tc"):
                            cells.append(" ".join(
                                t.text or "" for t in cell.iter() if t.tag.endswith("}t")))
                    out.append(" | ".join(c.strip() for c in cells))
    return "\n".join(out)


_RTF_SKIP = re.compile(r"\{\\(?:\*|fonttbl|colortbl|stylesheet|info|pict|header|footer)"
                       r"[^{}]*(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}[^{}]*)*\}")


def rtf_text(raw: str) -> str:
    """Minimal RTF reader (paragraphs, umlauts, unicode) — enough for doctor's letters."""
    t = _RTF_SKIP.sub("", raw)
    t = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252"),
               t)
    t = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), t)
    t = re.sub(r"\\(?:par|line|row)\b ?", "\n", t)
    t = re.sub(r"\\(?:tab|cell)\b ?", "\t", t)
    t = re.sub(r"\\([{}\\])", r"\1", t)
    t = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", t)
    t = t.replace("{", "").replace("}", "")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def html_text(raw: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", raw)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(t)).strip()


def _read_text(src: Path) -> str:
    raw = src.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _eml(src: Path) -> tuple[str, list[tuple[str, bytes]]]:
    msg = email.message_from_bytes(src.read_bytes(), policy=email.policy.default)
    head = [f"{k}: {msg[k]}" for k in ("From", "To", "Cc", "Date", "Subject") if msg[k]]
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        text = body.get_content()
        if body.get_content_type() == "text/html":
            text = html_text(text)
    attachments = []
    for part in msg.iter_attachments():
        name = part.get_filename()
        data = part.get_payload(decode=True)
        if name and data:
            attachments.append((Path(name).name, data))
    if attachments:
        head.append("Anhänge (separat in die Akte importiert): "
                    + ", ".join(n for n, _ in attachments))
    return "\n".join(head) + "\n\n" + text, attachments


# ------------------------------------------------------------------ PDF writing

def text_pdf(dest: Path, header: str, text: str, placeholder: bool = False) -> Path:
    paras = [p for p in re.split(r"\n", text)]
    body = "".join(f"<p>{html.escape(p) or '&nbsp;'}</p>" for p in paras)
    if placeholder:
        body = f'<p class="ph">{html.escape(text)}</p>'
    story = fitz.Story(html=f'<div class="hdr">{html.escape(header)}</div>{body}',
                       user_css=CSS)
    writer = fitz.DocumentWriter(str(dest))
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (50, 50, -50, -50)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return dest


def to_pdf(src: Path, orig_name: str, out_dir: Path) -> tuple[Path, list[tuple[str, bytes]], str]:
    """-> (text PDF, attachments, how). Never raises for unknown types: those get a
    placeholder page."""
    suffix = src.suffix.lower()
    label = KIND_LABEL.get(suffix, f"Datei im Format {suffix or 'ohne Endung'}")
    header = (f"Umgewandelt aus: {orig_name} ({label}). Das Original ist unverändert in der "
              "Akte gespeichert.")
    dest = out_dir / f"{src.stem}.converted.pdf"
    attachments: list[tuple[str, bytes]] = []
    try:
        if suffix in DOCX:
            text, how = _docx_text(src), "docx"
        elif suffix in RTF:
            text, how = rtf_text(_read_text(src)), "rtf"
        elif suffix in TEXT:
            text, how = _read_text(src), "text"
        elif suffix in HTML:
            text, how = html_text(_read_text(src)), "html"
        elif suffix in EML:
            (text, attachments), how = _eml(src), "eml"
        elif suffix in AUDIO:
            return text_pdf(dest, header, (
                f"{label}: {orig_name}. Eine Transkription ist in dieser Version nicht "
                "enthalten — Inhalt bitte manuell zusammenfassen (z. B. als Gesprächsnotiz "
                "im Reiter „Untersuchung“) oder als Aktenauszug-Eintrag ergänzen."),
                placeholder=True), [], "placeholder"
        else:
            raise ValueError("unbekanntes Format")
    except Exception as e:  # noqa: BLE001 — unreadable file: placeholder, not data loss
        return text_pdf(dest, header, (
            f"{label}: {orig_name} konnte nicht gelesen werden ({e}). Inhalt bitte manuell "
            "zusammenfassen oder als Aktenauszug-Eintrag ergänzen."),
            placeholder=True), [], "placeholder"
    if not text.strip():
        return text_pdf(dest, header, f"{label}: {orig_name} enthält keinen lesbaren Text.",
                        placeholder=True), attachments, "placeholder"
    return text_pdf(dest, header, text), attachments, how
