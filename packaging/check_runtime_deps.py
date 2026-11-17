# SPDX-License-Identifier: AGPL-3.0-or-later
"""CI gate: every DLL imported by the bundled native programs must be either in the
same folder or a guaranteed part of Windows. Catches e.g. a missing VC++ runtime
before it reaches a laptop where "the model does not start".

    uv run --with pefile python packaging/check_runtime_deps.py dist/DerGutachter/bin
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pefile

# Always present on Windows 10/11 (system DLLs and API sets).
SYSTEM = re.compile(
    r"^(api-ms-win-.*|ext-ms-.*|kernel32|kernelbase|user32|gdi32|advapi32|shell32|ole32|"
    r"oleaut32|ws2_32|bcrypt|bcryptprimitives|crypt32|secur32|shlwapi|comdlg32|comctl32|version|winmm|"
    r"psapi|dbghelp|ntdll|rpcrt4|setupapi|cfgmgr32|iphlpapi|userenv|wininet|winhttp|"
    r"normaliz|imm32|powrprof|dxgi|d3d11|d3d12|dwmapi|uxtheme|mswsock|dnsapi|ncrypt|"
    r"msvcrt|ucrtbase|winspool\.drv|opengl32|wldap32|netapi32|mpr|credui|"
    r"msimg32|usp10|dwrite|d2d1|windowscodecs|gdiplus|shcore|wintrust|"
    r"nvcuda|vulkan-1)\.dll$",  # GPU driver DLLs: present iff the GPU/driver is
    re.I,
)


def check(folder: Path) -> list[str]:
    local = {p.name.lower() for p in folder.iterdir()}
    problems = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in (".exe", ".dll"):
            continue
        try:
            pe = pefile.PE(str(f), fast_load=True)
            pe.parse_data_directories(directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        except pefile.PEFormatError:
            continue
        for imp in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            name = imp.dll.decode().lower()
            if name not in local and not SYSTEM.match(name):
                problems.append(f"{folder.name}/{f.name} needs {name}")
    return problems


def main() -> None:
    root = Path(sys.argv[1])
    problems = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        problems += check(folder)
    for p in problems:
        print("MISSING", p)
    if problems:
        raise SystemExit(f"{len(problems)} unresolved DLL dependencies")
    print("all native dependencies resolved")


if __name__ == "__main__":
    main()
