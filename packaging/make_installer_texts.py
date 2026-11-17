# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the installer's licence page: German disclaimer + licence notice.

The installer requires "I accept" before installing. Output is UTF-8 with BOM
(Inno Setup reads that as Unicode).   uv run python packaging/make_installer_texts.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "installer-license.txt"


def main() -> None:
    md = (ROOT / "DISCLAIMER.md").read_text(encoding="utf-8")
    german = md.split("\n---\n")[0]  # German part (binding wording for DE/AT/CH users)
    german = german.replace("*English version below.*\n", "")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", german)        # bold
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1", text)      # links
    text = re.sub(r"^#+ ", "", text, flags=re.M)           # headings
    text += (
        "\n\nLizenz\n\nDer Gutachter ist freie Software unter der GNU Affero General Public "
        "License, Version 3 oder später (AGPL-3.0-or-later). Der vollständige Lizenztext "
        "(LICENSE), die Lizenzen der Drittkomponenten (NOTICE) und dieser "
        "Haftungsausschluss (DISCLAIMER.md) liegen im Programmverzeichnis.\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("﻿" + text.replace("\n", "\r\n"), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
