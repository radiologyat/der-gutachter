# SPDX-License-Identifier: AGPL-3.0-or-later
# PyInstaller spec — onedir, windowed. Build from the repo root:
#   uv run --group build --group desktop pyinstaller packaging/gutachten.spec --noconfirm
# Output: dist/DerGutachter/  (DerGutachter.exe + _internal/). CI then copies the staged
# native runtime (packaging/fetch_runtime.py) to dist/DerGutachter/bin/.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 (provided by PyInstaller)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(ROOT / "src" / "gutachten" / "db" / "*.sql"), "gutachten/db"),
        (str(ROOT / "web" / "dist"), "web"),
        # legal texts, shown in the app and shipped with every copy
        (str(ROOT / "DISCLAIMER.md"), "."),
        (str(ROOT / "LICENSE"), "."),
        (str(ROOT / "NOTICE"), "."),
    ],
    hiddenimports=[
        *collect_submodules("gutachten"),
        *collect_submodules("uvicorn"),
    ],
    excludes=["tkinter", "pytest", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="DerGutachter",
    console=False,          # windowed: no console window
    icon=os.path.join(SPECPATH, "icon", "gutachter.ico"),  # "G" mark of the app header  # noqa: F821
    disable_windowed_traceback=False,
    upx=False,              # UPX-packed binaries trigger antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, name="DerGutachter", upx=False)  # noqa: F821
