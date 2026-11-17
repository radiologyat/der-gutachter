# SPDX-License-Identifier: AGPL-3.0-or-later
"""German/Austrian/Swiss date parsing — used to check that a date an LLM
reports is actually written in the source text.

Dates are ISO strings with precision: 'YYYY', 'YYYY-MM' or 'YYYY-MM-DD'.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

MONTHS = {
    # deutsch
    "januar": 1, "jänner": 1, "jaenner": 1, "jan": 1, "jän": 1,
    "februar": 2, "feber": 2, "feb": 2,
    "märz": 3, "maerz": 3, "mär": 3, "mrz": 3,
    "april": 4, "apr": 4,
    "mai": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
    # französisch
    "janvier": 1, "janv": 1,
    "février": 2, "fevrier": 2, "févr": 2, "fevr": 2,
    "mars": 3,
    "avril": 4, "avr": 4,
    "juin": 6,
    "juillet": 7, "juil": 7,
    "août": 8, "aout": 8,
    "septembre": 9,
    "octobre": 10, "oct": 10,
    "novembre": 11,
    "décembre": 12, "decembre": 12, "déc": 12, "dec": 12,
    # italienisch
    "gennaio": 1, "genn": 1,
    "febbraio": 2, "febbr": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6, "giu": 6,
    "luglio": 7, "lug": 7,
    "agosto": 8,
    "settembre": 9, "sett": 9,
    "ottobre": 10, "ott": 10,
    "dicembre": 12, "dic": 12,
}
_MONTH_RE = "|".join(sorted(map(re.escape, MONTHS), key=len, reverse=True))

_ISO_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")

# Ranges whose first part omits the year: "15.10.-18.10.2016", "15.-18.10.2016"
_RANGE_DM = re.compile(
    r"(?<!\d)(\d{1,2})\.(\d{1,2})\.\s*[-–]\s*"
    r"(?=\d{1,2}\.\d{1,2}\.(\d{4}|\d{2})(?!\d))")
_RANGE_D = re.compile(
    r"(?<!\d)(\d{1,2})\.\s*[-–]\s*"
    r"(?=\d{1,2}\.(\d{1,2})\.(\d{4}|\d{2})(?!\d))")

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 14.03.2021 · 14.3.21 · 14/03/2021 · 14-03-2021
    (re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)"), "dmy"),
    # 2021-03-14
    (re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"), "iso"),
    # 14. März 2021 · 14 Mär. 2021
    (re.compile(rf"(?<!\d)(\d{{1,2}})\.?\s*({_MONTH_RE})\.?\s+(\d{{4}})", re.I), "d_month_y"),
    # März 2021
    (re.compile(rf"(?<![\w.])({_MONTH_RE})\.?\s+(\d{{4}})", re.I), "month_y"),
    # 03/2021 · 03.2021
    (re.compile(r"(?<![\d./-])(\d{1,2})[./](\d{4})(?![\d./-])"), "my"),
]


@dataclass(frozen=True)
class FoundDate:
    iso: str        # with precision
    start: int
    end: int


def _year(y: str) -> int:
    n = int(y)
    if len(y) == 4:
        return n
    pivot = dt.date.today().year % 100 + 1
    return 2000 + n if n <= pivot else 1900 + n


def _valid(y: int, m: int, d: int | None) -> bool:
    try:
        dt.date(y, m, d or 1)
        return 1900 <= y <= 2100
    except ValueError:
        return False


def find_dates(text: str) -> list[FoundDate]:
    out: list[FoundDate] = []
    taken: list[tuple[int, int]] = []
    for m in _RANGE_DM.finditer(text):  # start of a range, year taken from its end
        d, mo, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        if _valid(y, mo, d):
            out.append(FoundDate(f"{y:04d}-{mo:02d}-{d:02d}", m.start(), m.end()))
            taken.append((m.start(), m.end()))
    for m in _RANGE_D.finditer(text):
        if any(s < m.end() and m.start() < e for s, e in taken):
            continue
        d, mo, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        if _valid(y, mo, d):
            out.append(FoundDate(f"{y:04d}-{mo:02d}-{d:02d}", m.start(), m.end()))
            taken.append((m.start(), m.end()))
    for rx, kind in _PATTERNS:
        for m in rx.finditer(text):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue  # already covered by a more precise pattern
            g = m.groups()
            if kind == "dmy":
                y, mo, d = _year(g[2]), int(g[1]), int(g[0])
            elif kind == "iso":
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            elif kind == "d_month_y":
                y, mo, d = int(g[2]), MONTHS[g[1].lower()], int(g[0])
            elif kind == "month_y":
                y, mo, d = int(g[1]), MONTHS[g[0].lower()], None
            else:  # my
                y, mo, d = int(g[1]), int(g[0]), None
            if not _valid(y, mo, d):
                continue
            iso = f"{y:04d}-{mo:02d}" + (f"-{d:02d}" if d else "")
            out.append(FoundDate(iso, m.start(), m.end()))
            taken.append((m.start(), m.end()))
    return sorted(out, key=lambda f: f.start)


def normalize_iso(value: str | None) -> str | None:
    """Accept 'YYYY', 'YYYY-MM', 'YYYY-MM-DD' (also German 'DD.MM.YYYY');
    return canonical ISO or None if invalid."""
    if not value:
        return None
    v = value.strip()
    m = _ISO_RE.match(v)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        if mo is None:
            return y if 1900 <= int(y) <= 2100 else None
        if not _valid(int(y), int(mo), int(d) if d else None):
            return None
        return v
    found = find_dates(v)
    if len(found) == 1 and found[0].end - found[0].start >= len(v) - 1:
        return found[0].iso
    return None


def date_supported(iso: str, text: str) -> bool:
    """True if `text` states the date at (at least) the claimed precision.
    '2021-03' is supported by '14.03.2021'; '2021-03-14' is NOT supported by
    'März 2021' (the day would be invented)."""
    iso = normalize_iso(iso) or ""
    if not iso:
        return False
    for f in find_dates(text):
        if f.iso.startswith(iso):
            return True
    if len(iso) == 4:
        return re.search(rf"(?<!\d){iso}(?!\d)", text) is not None
    return False
