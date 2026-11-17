# SPDX-License-Identifier: AGPL-3.0-or-later
"""Locate LLM-supplied quotes in the OCR text and turn them into citations.

"Keine Aussage ohne Fundstelle": an extracted fact is only kept if its `quote`
is actually found on the cited page(s). Matching is fuzzy because OCR text is
noisy (0/O, rn/m, broken umlauts, hyphenation at line ends), but strict enough
that a paraphrase or an invented sentence does not match.

The result maps the quote onto the OCR blocks it spans, so the UI can jump to
"Bl. N d. A." and highlight the region.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

DEFAULT_MIN_SCORE = 0.85
MIN_QUOTE_CHARS = 8  # shorter quotes match anywhere and prove nothing

_QUOTES = str.maketrans({"„": '"', "“": '"', "”": '"', "«": '"', "»": '"',
                         "‚": "'", "‘": "'", "’": "'", "–": "-", "—": "-"})
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Canonical form for comparison: NFC, casefold, unified quotes/dashes,
    single spaces."""
    t = unicodedata.normalize("NFC", text).translate(_QUOTES).casefold()
    return _WS.sub(" ", t).strip()


@dataclass
class Citation:
    page_id: int
    global_seq: int
    score: float
    matched_text: str
    block_ids: list[int] = field(default_factory=list)  # empty = page-level citation
    bbox: tuple[float, float, float, float] | None = None

    @property
    def label(self) -> str:
        return f"Bl. {self.global_seq} d. A."

    def to_json(self, quote: str) -> dict:
        """Shape stored in timeline_entries.citations / findings.source_*."""
        return {
            "page_id": self.page_id,
            "global_seq": self.global_seq,
            "block_id": self.block_ids[0] if self.block_ids else None,
            "block_ids": self.block_ids,
            "bbox": list(self.bbox) if self.bbox else None,
            "quote": quote,
            "score": self.score,
        }


@dataclass
class _Segment:
    block_id: int | None
    start: int
    end: int
    bbox: tuple[float, float, float, float] | None


def _page_segments(conn: sqlite3.Connection, page_id: int) -> tuple[str, list[_Segment]]:
    """Normalized page text plus the char span each OCR block occupies in it.

    Uses blocks of the latest successful OCR run. If the text was corrected by
    hand, blocks no longer reflect it — fall back to the page text as a single
    page-level segment.
    """
    pt = conn.execute(
        "SELECT text_md, source FROM page_text WHERE page_id=?", (page_id,)
    ).fetchone()
    blocks = []
    if not pt or pt["source"] != "manual":
        blocks = conn.execute(
            """SELECT id, text, x0, y0, x1, y1 FROM ocr_blocks
               WHERE page_id=? AND run_id = (
                   SELECT MAX(id) FROM ocr_runs WHERE page_id=? AND status='ok')
               ORDER BY seq""",
            (page_id, page_id),
        ).fetchall()
    if not blocks:
        text = normalize(pt["text_md"]) if pt else ""
        return text, [_Segment(None, 0, len(text), None)] if text else []

    parts: list[str] = []
    segs: list[_Segment] = []
    pos = 0
    for b in blocks:
        t = normalize(b["text"])
        if not t:
            continue
        if parts:
            # re-join words hyphenated across a line break: "Gonar-" + "throse"
            if parts[-1].endswith("-") and t[:1].isalpha() and t[:1].islower():
                parts[-1] = parts[-1][:-1]
                pos -= 1
                segs[-1].end -= 1
            else:
                parts.append(" ")
                pos += 1
        segs.append(_Segment(b["id"], pos, pos + len(t), (b["x0"], b["y0"], b["x1"], b["y1"])))
        parts.append(t)
        pos += len(t)
    return "".join(parts), segs


def _best_window(hay: str, needle: str, min_score: float) -> tuple[float, int, int]:
    """Best fuzzy match of `needle` in `hay` over word-aligned windows."""
    idx = hay.find(needle)
    if idx >= 0:
        return 1.0, idx, idx + len(needle)

    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", hay)]
    k = len(needle.split())
    best = (0.0, 0, 0)
    sm = SequenceMatcher(None, autojunk=False)
    sm.set_seq2(needle)
    for size in range(max(1, k - 2), k + 3):
        for i in range(0, max(0, len(words) - size) + 1):
            if i + size > len(words):
                break
            s, e = words[i][0], words[i + size - 1][1]
            sm.set_seq1(hay[s:e])
            if sm.real_quick_ratio() < min_score or sm.quick_ratio() < min_score:
                continue
            r = sm.ratio()
            if r > best[0]:
                best = (r, s, e)
    return best


def locate_quote(
    conn: sqlite3.Connection,
    page_ids: list[int],
    quote: str,
    min_score: float = DEFAULT_MIN_SCORE,
) -> Citation | None:
    """Find `quote` on any of `page_ids` (a document may span pages).
    Returns the best citation, or None if the quote is not in the Akte."""
    needle = normalize(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        return None
    best: Citation | None = None
    for pid in page_ids:
        page = conn.execute("SELECT global_seq FROM pages WHERE id=?", (pid,)).fetchone()
        if not page:
            continue
        hay, segs = _page_segments(conn, pid)
        if not hay:
            continue
        score, s, e = _best_window(hay, needle, min_score)
        if score < min_score or (best and score <= best.score):
            continue
        hit = [sg for sg in segs if sg.start < e and sg.end > s]
        ids = [sg.block_id for sg in hit if sg.block_id is not None]
        boxes = [sg.bbox for sg in hit if sg.bbox]
        bbox = (
            (min(b[0] for b in boxes), min(b[1] for b in boxes),
             max(b[2] for b in boxes), max(b[3] for b in boxes))
            if boxes else None
        )
        best = Citation(pid, page["global_seq"], round(score, 4), hay[s:e], ids, bbox)
        if score == 1.0:
            break
    return best
