# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage the native runtime shipped inside the Windows app: build/runtime/bin/

  llama-vulkan/   llama.cpp Vulkan build   (any GPU; fallback when CUDA unavailable)
  llama-cpu/      llama.cpp CPU build      (no usable GPU)
  tesseract/      Tesseract 5.4 + tessdata deu/eng/osd

The CUDA build (~650 MB with runtime) is NOT bundled: it is fetched by the app's
model setup only on machines with an NVIDIA GPU. Every file is pinned by version
and SHA-256 so a build is reproducible. Run on Windows (CI): needs 7-Zip for the
Tesseract NSIS installer.

    uv run python packaging/fetch_runtime.py [--out build/runtime]
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("download_models",
                                               ROOT / "scripts" / "download_models.py")
dm = importlib.util.module_from_spec(_spec)
sys.modules["download_models"] = dm
_spec.loader.exec_module(dm)

LLAMA_BUILD = dm.LLAMA_BUILD
LLAMA_VARIANTS = {"llama-vulkan": "win-vulkan-x64", "llama-cpu": "win-cpu-x64"}

TESSERACT = {
    "url": "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/"
           "tesseract-ocr-w64-setup-5.4.0.20240606.exe",
    "sha256": "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9",
}
TESSDATA_COMMIT = "ced78752cc61322fb554c280d13360b35b8684e4"
TESSDATA = {
    "deu": "896b3b4956503ab9daa10285db330881b2d74b70d889b79262cc534b9ec699a4",
    "eng": "daa0c97d651c19fba3b25e81317cd697e9908c8208090c94c3905381c23fc047",
    "osd": "e19f2ae860792fdf372cf48d8ce70ae5da3c4052962fe22e9de1f680c374bb0e",
}


def _seven_zip() -> str:
    for c in ("7z", r"C:\Program Files\7-Zip\7z.exe"):
        if shutil.which(c) or Path(c).exists():
            return c
    raise SystemExit("7-Zip not found (needed to unpack the Tesseract installer)")


def stage_llama(bin_dir: Path, cache: Path) -> None:
    assets = {a["name"]: a for a in dm.github_release(dm.LLAMA_REPO, LLAMA_BUILD)["assets"]}
    for folder, variant in LLAMA_VARIANTS.items():
        name = f"llama-{LLAMA_BUILD}-bin-{variant}.zip"
        a = assets[name]
        z = cache / name
        dm.download(a["browser_download_url"], z,
                    sha256=(a.get("digest") or "").removeprefix("sha256:") or None,
                    size=a.get("size"))
        target = bin_dir / folder
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            for m in zf.infolist():
                if not m.is_dir():
                    with zf.open(m) as src, (target / Path(m.filename).name).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        assert (target / "llama-server.exe").exists(), f"{folder}: llama-server.exe missing"
        print(f"  staged  {folder} ({name})")


# Microsoft Visual C++ runtime: llama.cpp is built with the dynamic MSVC CRT. A clean
# Windows install may not have it, so the DLLs are deployed app-locally next to each
# llama-server.exe (permitted by the VC++ redistributable licence).
VC_RUNTIME = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
              "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
              "concrt140.dll")


def stage_vc_runtime(bin_dir: Path) -> None:
    system32 = Path(r"C:\Windows\System32")
    found = [system32 / n for n in VC_RUNTIME if (system32 / n).exists()]
    if not any(f.name == "vcruntime140.dll" for f in found):
        raise SystemExit("VC++ runtime not found in System32 (needed for app-local copy)")
    for folder in LLAMA_VARIANTS:
        for f in found:
            shutil.copy2(f, bin_dir / folder / f.name)
    print(f"  staged  VC++ runtime ({len(found)} DLLs) into {', '.join(LLAMA_VARIANTS)}")


def stage_tesseract(bin_dir: Path, cache: Path) -> None:
    exe = cache / Path(TESSERACT["url"]).name
    dm.download(TESSERACT["url"], exe, sha256=TESSERACT["sha256"])
    target = bin_dir / "tesseract"
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run([_seven_zip(), "x", "-y", f"-o{target}", str(exe)], check=True,
                   stdout=subprocess.DEVNULL)
    shutil.rmtree(target / "$PLUGINSDIR", ignore_errors=True)
    for junk in target.glob("*uninstall*"):
        junk.unlink()
    tessdata = target / "tessdata"
    tessdata.mkdir(exist_ok=True)
    for f in tessdata.glob("*.traineddata"):  # keep only what we pin
        f.unlink()
    base = f"https://github.com/tesseract-ocr/tessdata/raw/{TESSDATA_COMMIT}"
    for lang, sha in TESSDATA.items():
        dm.download(f"{base}/{lang}.traineddata", tessdata / f"{lang}.traineddata", sha256=sha)
    assert (target / "tesseract.exe").exists(), "tesseract.exe missing after unpack"
    print("  staged  tesseract")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "runtime")
    args = ap.parse_args()
    dm.MODELS = args.out  # download() prints paths relative to this
    bin_dir, cache = args.out / "bin", args.out / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    stage_llama(bin_dir, cache)
    stage_vc_runtime(bin_dir)
    stage_tesseract(bin_dir, cache)
    print("runtime staged in", bin_dir)


if __name__ == "__main__":
    main()
