# SPDX-License-Identifier: AGPL-3.0-or-later
"""ICD-10 (GM, as used in Switzerland): format check, a short list of common
orthopaedic codes, and — once imported — the complete official catalogue.

The catalogue is NOT bundled: the BfArM download comes with its own usage terms.
The user downloads the ClaML/XML file from bfarm.de and imports it in the setup
screen; from then on codes are checked for existence, not just format.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from . import config

FORMAT = re.compile(r"^[A-TV-Z][0-9]{2}(\.[0-9]{1,2})?[+*!†]?$")

COMMON: dict[str, str] = {
    # Knie
    "M17.0": "Primäre Gonarthrose, beidseitig",
    "M17.1": "Sonstige primäre Gonarthrose",
    "M17.3": "Sonstige posttraumatische Gonarthrose",
    "M23.2": "Meniskusschädigung durch alten Riss oder alte Verletzung",
    "M23.3": "Sonstige Meniskusschädigungen",
    "M22.4": "Chondromalacia patellae",
    "S83.2": "Meniskusriss, akut",
    "S83.5": "Verstauchung und Zerrung des Kniegelenkes mit Beteiligung des Kreuzbandes",
    "S83.4": "Verstauchung und Zerrung des Kniegelenkes mit Beteiligung des Seitenbandes",
    "S83.6": "Verstauchung und Zerrung sonstiger Teile des Kniegelenkes",
    "S80.0": "Prellung des Knies",
    "S82.1": "Fraktur des proximalen Endes der Tibia",
    "Z96.6": "Vorhandensein von orthopädischen Gelenkimplantaten",
    # Hüfte / Becken
    "M16.0": "Primäre Koxarthrose, beidseitig",
    "M16.1": "Sonstige primäre Koxarthrose",
    "S72.0": "Schenkelhalsfraktur",
    # Schulter / Arm
    "M75.1": "Läsionen der Rotatorenmanschette",
    "M75.4": "Impingement-Syndrom der Schulter",
    "M19.01": "Primäre Arthrose sonstiger Gelenke: Schulterregion",
    "S43.0": "Luxation des Schultergelenkes",
    "S43.1": "Luxation des Akromioklavikulargelenkes",
    "S46.0": "Verletzung der Muskeln und Sehnen der Rotatorenmanschette",
    "S42.0": "Fraktur der Klavikula",
    "S42.2": "Fraktur des proximalen Endes des Humerus",
    "S52.5": "Distale Fraktur des Radius",
    # Wirbelsäule
    "M47.8": "Sonstige Spondylose",
    "M48.0": "Spinal(kanal)stenose",
    "M50.1": "Zervikaler Bandscheibenschaden mit Radikulopathie",
    "M51.1": "Lumbale und sonstige Bandscheibenschäden mit Radikulopathie",
    "M51.2": "Sonstige näher bezeichnete Bandscheibenverlagerung",
    "M54.2": "Zervikalneuralgie",
    "M54.5": "Kreuzschmerz",
    "M54.4": "Lumboischialgie",
    "S13.4": "Verstauchung und Zerrung der Halswirbelsäule",
    "S32.0": "Fraktur eines Lendenwirbels",
    # Fuss / Sprunggelenk
    "S82.6": "Fraktur des Aussenknöchels",
    "S93.4": "Verstauchung und Zerrung des oberen Sprunggelenkes",
    "S86.0": "Verletzung der Achillessehne",
    "M19.07": "Primäre Arthrose sonstiger Gelenke: Knöchel und Fuss",
    # allgemein
    "M25.5": "Gelenkschmerz",
    "M79.6": "Schmerzen in den Extremitäten",
    "G56.0": "Karpaltunnel-Syndrom",
    "I80.2": "Thrombose, Phlebitis und Thrombophlebitis tiefer Gefässe der unteren Extremitäten",
    "I26.9": "Lungenembolie ohne Angabe eines akuten Cor pulmonale",
}


def catalog_path() -> Path:
    return config.MODELS_DIR / "icd10gm.json"


@lru_cache(maxsize=4)
def _load(path: str, _mtime: float) -> dict:  # mtime: cache key, reload after import
    return json.loads(Path(path).read_text(encoding="utf-8"))


def catalog() -> dict | None:
    """{"version": ..., "codes": {code: title}} or None if not imported."""
    p = catalog_path()
    return _load(str(p), p.stat().st_mtime) if p.exists() else None


def import_claml(src: Path) -> dict:
    """Import the official ICD-10-GM ClaML file (BfArM) — categories with their
    preferred label. Streaming parse; the input is a local file the user chose."""
    codes: dict[str, str] = {}
    version = None
    for _ev, el in ET.iterparse(src, events=("end",)):
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "Title" and version is None:
            version = (el.get("version") or "") + " " + "".join(el.itertext()).strip()
        elif tag == "Class":
            if el.get("kind") == "category" and (code := el.get("code")):
                for rub in el.iter():
                    if rub.tag.rsplit("}", 1)[-1] == "Rubric" and rub.get("kind") == "preferred":
                        codes[code] = " ".join("".join(rub.itertext()).split())
                        break
            el.clear()
    if len(codes) < 100:
        raise ValueError(f"Keine gültige ICD-10-GM-ClaML-Datei ({len(codes)} Codes gefunden)")
    data = {"version": (version or "").strip() or "ICD-10-GM", "codes": codes}
    p = catalog_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return {"version": data["version"], "codes": len(codes)}


def exists(code: str | None) -> bool | None:
    """True/False if the catalogue is imported, None if unknown (no catalogue)."""
    cat = catalog()
    c = normalize(code)
    if cat is None or not c:
        return None
    return c.rstrip("+*!†") in cat["codes"]


def normalize(code: str | None) -> str | None:
    if not code:
        return None
    c = code.strip().upper().replace(" ", "")
    if re.fullmatch(r"[A-Z][0-9]{3,4}", c):  # "M171" -> "M17.1"
        c = f"{c[:3]}.{c[3:]}"
    return c


def valid_format(code: str | None) -> bool:
    c = normalize(code)
    return bool(c and FORMAT.match(c))


def search(q: str, limit: int = 12) -> list[dict]:
    q = q.strip().lower()
    if not q:
        return []
    cat = catalog()
    source = cat["codes"] if cat else COMMON
    cq = q.replace(" ", "")
    hits = [{"code": c, "text": t} for c, t in source.items() if c.lower().startswith(cq)]
    if len(hits) < limit:
        hits += [{"code": c, "text": t} for c, t in source.items()
                 if q in t.lower() and not c.lower().startswith(cq)]
    return hits[:limit]
