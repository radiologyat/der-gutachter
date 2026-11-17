# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paths and runtime configuration — development checkout and installed app.

Development (repo checkout): data, models and binaries live under the repo root,
as before. Installed app (PyInstaller bundle, `sys.frozen`):

  <install dir>/DerGutachter.exe     launcher            (APP_DIR)
  <install dir>/_internal/           Python + web UI     (RESOURCE_DIR)
  <install dir>/bin/llama-vulkan|cpu llama.cpp builds shipped with the app
  <install dir>/bin/tesseract/       Tesseract + tessdata
  %LOCALAPPDATA%/DerGutachter/models/ model pack: GGUF + bin/llama-cuda
  %LOCALAPPDATA%/DerGutachter/data/  cases (default; user may pick e.g. a BitLocker drive)

Patient data never lives in the install directory: it is read-only for the user
and removed on uninstall. Overrides: GUTACHTEN_HOME, GUTACHTEN_MODELS, or
settings.json in the per-user config directory.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
FROZEN = bool(getattr(sys, "frozen", False))

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else ROOT
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", ROOT)) if FROZEN else ROOT

APP_NAME = "DerGutachter"


def user_config_dir() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gutachten"


def user_data_dir() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "gutachten"


SETTINGS_FILE = Path(os.environ.get("GUTACHTEN_SETTINGS", user_config_dir() / "settings.json"))


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(updates: dict) -> None:
    data = {**load_settings(), **updates}
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


_settings = load_settings() if FROZEN or os.environ.get("GUTACHTEN_USE_SETTINGS") else {}


def _path(env: str, setting: str, frozen_default: Path, dev_default: Path) -> Path:
    if v := os.environ.get(env):
        return Path(v)
    if v := _settings.get(setting):
        return Path(v)
    return frozen_default if FROZEN else dev_default


# Mutable patient data (cases, logs).
DATA_HOME = _path("GUTACHTEN_HOME", "data_home", user_data_dir() / "data", ROOT)
CASES_DIR = DATA_HOME / "cases"
LOGS_DIR = DATA_HOME / "logs"

# Model weights are NOT patient data.
MODELS_DIR = _path("GUTACHTEN_MODELS", "models_dir", user_data_dir() / "models", ROOT / "models")

WEB_DIST = RESOURCE_DIR / "web" if FROZEN else ROOT / "web" / "dist"
APP_BIN = APP_DIR / "bin"  # binaries shipped inside the app (frozen)


def _tessdata_dir() -> Path:
    if v := os.environ.get("GUTACHTEN_TESSDATA"):
        return Path(v)
    bundled = APP_BIN / "tesseract" / "tessdata"
    if FROZEN and (bundled / "deu.traineddata").exists():
        return bundled
    return MODELS_DIR / "tessdata"


TESSDATA_DIR = _tessdata_dir()

LLAMA_HOST = "127.0.0.1"
LLAMA_PORT = int(os.environ.get("GUTACHTEN_LLAMA_PORT", "8078"))

API_HOST = os.environ.get("GUTACHTEN_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("GUTACHTEN_API_PORT", "8077"))

# Language model for all text stages (Gemma 4 12B, chosen 2026-11-17 after a model
# comparison). Path to a GGUF file; if unset the first
# *.gguf under models/gguf/gemma4-12b/ is used. An already running
# llama-server on LLAMA_PORT is used as-is.
EXTRACT_MODEL = os.environ.get("GUTACHTEN_EXTRACT_MODEL")
EXTRACT_MODEL_DIR = MODELS_DIR / "gguf" / "gemma4-12b"
# 8 GB VRAM: ~7 GB weights leave room for a modest KV cache only.
EXTRACT_CTX = int(os.environ.get("GUTACHTEN_EXTRACT_CTX", "16384"))

RENDER_DPI = 300  # page images for OCR + viewer
MAX_UPLOAD_MB = int(os.environ.get("GUTACHTEN_MAX_UPLOAD_MB", "600"))

# Pages whose OCR confidence falls below this go to the review queue.
OCR_REVIEW_THRESHOLD = float(os.environ.get("GUTACHTEN_OCR_REVIEW_THRESHOLD", "0.72"))

CUDA_REQUIRED = (13, 5)  # the bundled CUDA llama.cpp build; RTX 50xx needs >= 12.8


@lru_cache(maxsize=1)
def nvidia_smi() -> str | None:
    """Locate nvidia-smi. It is not always on PATH (portable start, some laptop
    drivers): System32, the NVSMI folder and the driver store are searched too."""
    if found := shutil.which("nvidia-smi"):
        return found
    if not IS_WINDOWS:
        return None
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    for p in (root / "System32" / "nvidia-smi.exe",
              pf / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"):
        if p.exists():
            return str(p)
    store = root / "System32" / "DriverStore" / "FileRepository"
    try:
        hits = sorted(store.glob("nv*/nvidia-smi.exe"), key=lambda p: p.stat().st_mtime)
    except OSError:
        hits = []
    return str(hits[-1]) if hits else None


def run_nvidia_smi(*args: str) -> tuple[str | None, str]:
    """-> (stdout or None, diagnostic text). The first call can take long while a
    laptop wakes its dedicated GPU, hence the generous timeout."""
    exe = nvidia_smi()
    if not exe:
        return None, "nvidia-smi nicht gefunden (PATH, System32, NVSMI, DriverStore)"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"{exe}: {type(e).__name__} {e}"
    if r.returncode != 0:
        return None, f"{exe}: Exit {r.returncode} {(r.stderr or r.stdout).strip()[:200]}"
    return r.stdout, exe


def nvidia_cuda_version() -> tuple[int, int] | None:
    """Highest CUDA version the installed NVIDIA driver supports, via nvidia-smi."""
    out, _ = run_nvidia_smi()
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def llama_server_candidates() -> list[Path]:
    """Bundled llama-server builds, best first for this machine."""
    exe = "llama-server.exe" if IS_WINDOWS else "llama-server"
    out: list[Path] = []
    cuda = nvidia_cuda_version() if IS_WINDOWS else None
    if cuda and cuda >= CUDA_REQUIRED:
        out.append(MODELS_DIR / "bin" / "llama-cuda" / exe)   # from the model pack
    out.append(MODELS_DIR / "bin" / "llama" / exe)            # dev: download_models.py
    out += [APP_BIN / "llama-vulkan" / exe, APP_BIN / "llama-cpu" / exe]
    return out


def llama_server_bins() -> list[str]:
    """All usable candidates, best first (the server falls back if one won't start)."""
    if env := os.environ.get("LLAMA_SERVER_BIN"):
        return [env]
    out = [str(p) for p in llama_server_candidates() if p.exists()]
    if (found := shutil.which("llama-server")) and found not in out:
        out.append(found)
    return out


def llama_server_bin() -> str | None:
    """llama-server: $LLAMA_SERVER_BIN, else the best bundled build, else PATH."""
    if env := os.environ.get("LLAMA_SERVER_BIN"):
        return env
    for p in llama_server_candidates():
        if p.exists():
            return str(p)
    return shutil.which("llama-server")


def tesseract_cmd() -> str | None:
    """tesseract: $TESSERACT_CMD, else bundled, else PATH, else the default
    Windows install locations (the UB-Mannheim installer does not touch PATH)."""
    if env := os.environ.get("TESSERACT_CMD"):
        return env
    exe = "tesseract.exe" if IS_WINDOWS else "tesseract"
    if (bundled := APP_BIN / "tesseract" / exe).exists():
        return str(bundled)
    if found := shutil.which("tesseract"):
        return found
    if IS_WINDOWS:
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                     os.environ.get("LOCALAPPDATA") and
                     str(Path(os.environ["LOCALAPPDATA"]) / "Programs")):
            if base and (exe_p := Path(base) / "Tesseract-OCR" / "tesseract.exe").exists():
                return str(exe_p)
    return None


def case_dir(case_id: str) -> Path:
    return CASES_DIR / case_id


def ensure_dirs() -> None:
    for d in (CASES_DIR, MODELS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
