# SPDX-License-Identifier: AGPL-3.0-or-later
"""Download local models and the llama.cpp runtime - Windows 11, macOS, Linux.

    uv run python scripts/download_models.py                # everything for this machine
    uv run python scripts/download_models.py --only tessdata extract
    uv run python scripts/download_models.py --check        # show what's missing

Everything lands under models/ (gitignored, override with GUTACHTEN_MODELS).
These are one-time setup downloads; the app itself never goes online.

- resumable downloads (HTTP Range) - a dropped connection doesn't restart 6 GB
- SHA-256 verified against Hugging Face LFS / GitHub release digests
- llama.cpp pinned to a tested build; on Windows the variant is picked from the
  NVIDIA driver: CUDA 13.5 (needed for RTX 50xx/Blackwell) -> Vulkan fallback -> CPU
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
MODELS = Path(os.environ.get("GUTACHTEN_MODELS", ROOT / "models"))
BIN = MODELS / "bin"

LLAMA_BUILD = "b12406"  # pinned; bump deliberately after re-running the eval
LLAMA_REPO = "ggml-org/llama.cpp"
CUDA_VARIANT = "13.5"   # Blackwell (sm_120) needs CUDA >= 12.8; 12.4 builds won't run
TESS_URL = "https://github.com/tesseract-ocr/tessdata/raw/main/{lang}.traineddata"


@dataclass(frozen=True)
class HfFile:
    role: str
    repo: str
    filename: str
    dest: str  # sub-directory under models/gguf


HF_FILES = [
    HfFile("extract", "google/gemma-4-12B-it-qat-q4_0-gguf", "gemma-4-12b-it-qat-q4_0.gguf",
           "gemma4-12b"),
]
DEFAULT_ROLES = ["tessdata", "llama", "extract"]


# ------------------------------------------------------------------ download core


def github_release(repo: str, tag: str, attempts: int = 5) -> dict:
    """Release metadata from the GitHub API. Uses GITHUB_TOKEN when set (CI: 1000
    requests/h instead of 60 per shared runner IP) and retries on rate limits —
    unauthenticated calls failed builds with "403 rate limit exceeded"."""
    import os
    import time

    headers = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    for i in range(attempts):
        r = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        if r.status_code in (403, 429, 500, 502, 503, 504) and i < attempts - 1:
            reset = r.headers.get("x-ratelimit-reset")
            wait = min(max(int(reset) - int(time.time()), 5), 120) if reset and \
                r.headers.get("x-ratelimit-remaining") == "0" else 10 * (i + 1)
            print(f"  GitHub API {r.status_code} — retry in {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, sha256: str | None = None, size: int | None = None) -> None:
    """Resumable download to dest (via dest.part), verified if sha256 given."""
    if dest.exists() and (sha256 is None or _sha256(dest) == sha256):
        print(f"  ok      {dest.relative_to(MODELS)}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=300)) as http:
        with http.stream("GET", url, headers=headers) as r:
            if r.status_code == 416:  # already complete
                pass
            else:
                r.raise_for_status()
                if have and r.status_code != 206:  # server ignored Range
                    have = 0
                total = size or (int(r.headers.get("content-length", 0)) + have) or None
                mode = "ab" if have else "wb"
                done = have
                with part.open(mode) as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            print(f"\r  ...     {dest.name} {100 * done // total:3d}%"
                                  f" ({done >> 20} / {total >> 20} MB)", end="", flush=True)
                print()
    if sha256:
        got = _sha256(part)
        if got != sha256:
            part.unlink()
            raise SystemExit(f"SHA-256 mismatch for {dest.name}: {got} != {sha256}")
    os.replace(part, dest)
    print(f"  done    {dest.relative_to(MODELS)}")


# ------------------------------------------------------------------ tessdata

def get_tessdata() -> None:
    print("== Tesseract traineddata (deu, eng, osd)")
    for lang in ("deu", "eng", "osd"):
        download(TESS_URL.format(lang=lang), MODELS / "tessdata" / f"{lang}.traineddata")


# ------------------------------------------------------------------ GGUF models

def hf_meta(repo: str, filename: str) -> tuple[str | None, int | None]:
    r = httpx.get(f"https://huggingface.co/api/models/{repo}/tree/main", timeout=30)
    r.raise_for_status()
    for e in r.json():
        if e.get("path") == filename:
            lfs = e.get("lfs") or {}
            return lfs.get("oid"), lfs.get("size") or e.get("size")
    raise SystemExit(f"{filename} not found in {repo} - repo layout changed?")


def get_gguf(role: str) -> None:
    for f in (x for x in HF_FILES if x.role == role):
        print(f"== GGUF {role}: {f.repo}/{f.filename}")
        sha, size = hf_meta(f.repo, f.filename)
        free = shutil.disk_usage(MODELS if MODELS.exists() else ROOT).free
        if size and free < size * 1.05:
            raise SystemExit(f"Not enough disk space: need {size >> 30} GB, free {free >> 30} GB")
        url = f"https://huggingface.co/{f.repo}/resolve/main/{f.filename}"
        download(url, MODELS / "gguf" / f.dest / f.filename, sha256=sha, size=size)


# ------------------------------------------------------------------ llama.cpp runtime

def nvidia_cuda_version() -> tuple[int, int] | None:
    """Highest CUDA version the installed NVIDIA driver supports (from nvidia-smi)."""
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def pick_windows_assets(cuda: tuple[int, int] | None, build: str = LLAMA_BUILD) -> list[str]:
    """Asset names to install for Windows x64 given the driver's CUDA version."""
    need = tuple(int(x) for x in CUDA_VARIANT.split("."))
    if cuda and cuda >= need:
        return [f"llama-{build}-bin-win-cuda-{CUDA_VARIANT}-x64.zip",
                f"cudart-llama-bin-win-cuda-{CUDA_VARIANT}-x64.zip"]
    if cuda:  # NVIDIA GPU but driver too old for CUDA 13.5: Vulkan still uses the GPU
        return [f"llama-{build}-bin-win-vulkan-x64.zip"]
    return [f"llama-{build}-bin-win-cpu-x64.zip"]


def get_llama() -> None:
    system = platform.system()
    print(f"== llama.cpp {LLAMA_BUILD} ({system})")
    if system != "Windows":
        if shutil.which("llama-server"):
            print(f"  ok      llama-server on PATH ({shutil.which('llama-server')})")
        else:
            hint = "brew install llama.cpp" if system == "Darwin" else "build llama.cpp"
            print(f"  missing llama-server - install it: {hint}")
        return
    cuda = nvidia_cuda_version()
    assets = pick_windows_assets(cuda)
    if cuda and "vulkan" in assets[0]:
        print(f"  NOTE: driver supports CUDA {cuda[0]}.{cuda[1]} < {CUDA_VARIANT}. Using Vulkan;"
              " update the NVIDIA driver for the faster CUDA build, then re-run.")
    by_name = {a["name"]: a for a in github_release(LLAMA_REPO, LLAMA_BUILD)["assets"]}
    target = BIN / "llama"
    marker = target / ".installed"
    wanted = ",".join(assets)
    if marker.exists() and marker.read_text(encoding="utf-8") == wanted:
        print(f"  ok      {target.relative_to(MODELS)} ({wanted})")
        return
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in assets:
        a = by_name.get(name)
        if not a:
            raise SystemExit(f"{name} not in release {LLAMA_BUILD}")
        digest = (a.get("digest") or "").removeprefix("sha256:") or None
        z = BIN / "downloads" / name
        download(a["browser_download_url"], z, sha256=digest, size=a.get("size"))
        with zipfile.ZipFile(z) as zf:
            for m in zf.infolist():  # flatten: all DLLs must sit next to the exe
                if m.is_dir():
                    continue
                out = target / Path(m.filename).name
                with zf.open(m) as src, out.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    if not (target / "llama-server.exe").exists():
        raise SystemExit("llama-server.exe missing after extraction")
    marker.write_text(wanted, encoding="utf-8")
    print(f"  done    {target.relative_to(MODELS)}\\llama-server.exe")


# ------------------------------------------------------------------ main

def check() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from gutachten import config

    missing = 0
    rows = [
        ("Tesseract binary", config.tesseract_cmd()),
        ("tessdata deu", (MODELS / "tessdata" / "deu.traineddata").exists() or None),
        ("llama-server", config.llama_server_bin()),
        ("Extraction model", next((MODELS / "gguf" / "gemma4-12b").glob("*.gguf"), None)),
    ]
    for name, val in rows:
        print(f"  {'ok     ' if val else 'MISSING'} {name}{': ' + str(val) if val else ''}")
        missing += not val
    return 1 if missing else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", choices=["tessdata", "llama", "extract"])
    ap.add_argument("--check", action="store_true", help="report what is installed")
    args = ap.parse_args()
    if args.check:
        raise SystemExit(check())
    roles = args.only or DEFAULT_ROLES
    if "tessdata" in roles:
        get_tessdata()
    if "llama" in roles:
        get_llama()
    if "extract" in roles:
        get_gguf("extract")
    print("Done. Model files live under", MODELS)


if __name__ == "__main__":
    main()
