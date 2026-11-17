# SPDX-License-Identifier: AGPL-3.0-or-later
"""Model setup: what to install on this machine, download or offline import.

Catalog entries are pinned (URL, size, SHA-256) so a download or an import from
a USB stick is verified before it is used. The only network access of the whole
application happens here, and only when the user starts it.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .downloads import (
    CancelToken,
    copy_verified,
    download,
    extract_flat,
    hf_meta,
    hf_url,
)

LLAMA_BUILD = "b12406"
GH = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}"


@dataclass(frozen=True)
class FileSpec:
    url: str
    name: str                   # file name (also what offline import looks for)
    size: int
    sha256: str | None          # None: fetched from Hugging Face at download time
    dest: str                   # relative to MODELS_DIR (file, or folder if unpack)
    unpack: bool = False
    hf: tuple[str, str] | None = None  # (repo, filename) for late checksum lookup


@dataclass(frozen=True)
class Item:
    id: str
    label: str
    description: str
    files: tuple[FileSpec, ...]
    recommended: bool = False
    min_ram_gb: int = 0
    windows_nvidia_only: bool = False
    marker: str | None = None   # for unpacked items: folder/.installed
    extra: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)


GEMMA = ("google/gemma-4-12B-it-qat-q4_0-gguf", "gemma-4-12b-it-qat-q4_0.gguf")

CATALOG: tuple[Item, ...] = (
    Item(
        id="extract",
        label="Sprachmodell Gemma 4 12B",
        description="Für Gutachtenauftrag, Register, Extraktion, KI-Prüfung und "
                    "KI-Vorentwurf. Benötigt rund 7 GB; auf einer 8-GB-Grafikkarte "
                    "weitgehend auf der GPU. Erforderlich.",
        recommended=True,
        files=(FileSpec(
            url=hf_url(*GEMMA), name=GEMMA[1], size=6_975_879_296,
            sha256="93567e57a8fe10b23569b9d9ec38cd005deedf71e29477c421a4b83f418a538b",
            dest=f"gguf/gemma4-12b/{GEMMA[1]}", hf=GEMMA,
        ),),
    ),
    Item(
        id="cuda",
        label="GPU-Beschleunigung (NVIDIA CUDA 13.5)",
        description="Deutlich schneller als die mitgelieferte Vulkan-Version. Nur für "
                    "NVIDIA-Grafikkarten mit aktuellem Treiber.",
        recommended=True, windows_nvidia_only=True, marker="bin/llama-cuda/.installed",
        files=(
            FileSpec(url=f"{GH}/llama-{LLAMA_BUILD}-bin-win-cuda-13.5-x64.zip",
                     name=f"llama-{LLAMA_BUILD}-bin-win-cuda-13.5-x64.zip", size=203_425_790,
                     sha256="bcd2f58e576ba4e76968199a995ab074f51618cd870a957856a3b95644724eca",
                     dest="bin/llama-cuda", unpack=True),
            FileSpec(url=f"{GH}/cudart-llama-bin-win-cuda-13.5-x64.zip",
                     name="cudart-llama-bin-win-cuda-13.5-x64.zip", size=426_314_199,
                     sha256="c2bf4cc202bfbaaa7a0b75f5082457c3811326947bb216059b72839d844e9cba",
                     dest="bin/llama-cuda", unpack=True),
        ),
    ),
)
BY_ID = {i.id: i for i in CATALOG}


# ------------------------------------------------------------------ system

def ram_gb() -> float | None:
    try:
        if config.IS_WINDOWS:
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2**30
        if config.IS_MAC:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                 text=True, timeout=5).stdout
            return int(out.strip()) / 2**30
        with open("/proc/meminfo", encoding="utf-8") as f:
            kb = int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1))
        return kb / 2**20
    except Exception:
        return None


def _windows_gpu_names() -> list[str]:
    """Display adapters as Windows sees them (works without nvidia-smi)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [x.strip() for x in out.splitlines() if x.strip()]


def nvidia_gpu() -> dict | None:
    """NVIDIA GPU with VRAM and supported CUDA version. Falls back to the Windows
    adapter list when nvidia-smi cannot be run, so a laptop with an NVIDIA GPU is
    never reported as "no NVIDIA" just because the tool was not found."""
    out, diag = config.run_nvidia_smi("--query-gpu=name,memory.total",
                                      "--format=csv,noheader,nounits")
    if out and out.strip():
        name, mem = [x.strip() for x in out.strip().splitlines()[0].split(",")[:2]]
        cuda = config.nvidia_cuda_version()
        return {"name": name, "vram_gb": round(int(mem) / 1024, 1),
                "cuda": f"{cuda[0]}.{cuda[1]}" if cuda else None,
                "cuda_ok": bool(cuda and cuda >= config.CUDA_REQUIRED),
                "detected_by": "nvidia-smi", "diag": diag}
    if config.IS_WINDOWS:
        names = [n for n in _windows_gpu_names() if "nvidia" in n.lower()]
        if names:
            return {"name": names[0], "vram_gb": None, "cuda": None, "cuda_ok": None,
                    "detected_by": "Windows", "diag": diag}
    return None


def gpu_diagnostics() -> dict:
    """Everything the GPU check saw — shown in the setup page and the log."""
    out, diag = config.run_nvidia_smi()
    return {"nvidia_smi": config.nvidia_smi(), "nvidia_smi_result": diag,
            "nvidia_smi_head": (out or "")[:600],
            "adapters": _windows_gpu_names() if config.IS_WINDOWS else []}


def system_info() -> dict:
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    ram = ram_gb()
    return {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "ram_gb": round(ram, 1) if ram else None,
        "gpu": nvidia_gpu(),
        "apple_silicon": config.IS_MAC and platform.machine() == "arm64",
        "disk_free_gb": round(shutil.disk_usage(config.MODELS_DIR).free / 2**30, 1),
        "models_dir": str(config.MODELS_DIR),
        "llama_server": config.llama_server_bin(),
    }


# ------------------------------------------------------------------ status

def is_installed(item: Item) -> bool:
    if item.marker:
        m = config.MODELS_DIR / item.marker
        return m.exists() and m.read_text(encoding="utf-8").strip() == _marker_text(item)
    return all((p := config.MODELS_DIR / f.dest).exists() and p.stat().st_size == f.size
               for f in item.files)


def _marker_text(item: Item) -> str:
    return ",".join(f.name for f in item.files)


def availability(item: Item, sysinfo: dict) -> tuple[bool, str | None]:
    if item.windows_nvidia_only:
        if not config.IS_WINDOWS:
            return False, "Nur unter Windows mit NVIDIA-Grafikkarte"
        gpu = sysinfo.get("gpu")
        if not gpu:
            return False, ("Keine NVIDIA-Grafikkarte gefunden — "
                           "die mitgelieferte Version wird genutzt")
        if gpu["cuda_ok"] is None:
            pass  # NVIDIA seen by Windows, CUDA version unknown: allow — the server
            # falls back to the Vulkan build at start if CUDA does not work
        elif not gpu["cuda_ok"]:
            return False, (f"Grafiktreiber unterstützt CUDA {gpu['cuda'] or '?'}; benötigt 13.5 — "
                           "bitte NVIDIA-Treiber aktualisieren")
    if item.min_ram_gb and (sysinfo.get("ram_gb") or 0) < item.min_ram_gb:
        return False, (f"Zu wenig Arbeitsspeicher ({sysinfo.get('ram_gb')} GB, "
                       f"benötigt {item.min_ram_gb + 2} GB)")
    if not is_installed(item):
        need = item.size * 1.05 / 2**30
        if sysinfo["disk_free_gb"] < need:
            return False, (f"Zu wenig Speicherplatz ({sysinfo['disk_free_gb']} GB frei, "
                           f"benötigt {need:.1f} GB)")
    return True, None


def status() -> dict:
    info = system_info()
    items = []
    for it in CATALOG:
        ok, reason = availability(it, info)
        inst = is_installed(it)
        items.append({
            "id": it.id, "label": it.label, "description": it.description,
            "size_gb": round(it.size / 2**30, 2), "installed": inst,
            "available": ok, "reason": reason,
            "recommended": it.recommended and ok and not inst,
        })
    ready = BY_ID["extract"] and is_installed(BY_ID["extract"])
    return {"system": info, "items": items, "ready": bool(ready)}


# ------------------------------------------------------------------ install / import

class _Progress:
    """Aggregates per-file progress into one job progress (MB)."""

    def __init__(self, job, files: list[FileSpec]):
        self.job, self.total = job, sum(f.size for f in files)
        self.base = 0
        if job:
            job.total, job.done = self.total // 2**20, 0

    def file(self, f: FileSpec, verb: str):
        if self.job:
            self.job.step = f"{verb}: {f.name}"

        def cb(done: int, _total: int | None) -> None:
            if self.job:
                self.job.done = (self.base + done) // 2**20
        return cb

    def finished(self, f: FileSpec):
        self.base += f.size
        if self.job:
            self.job.done = self.base // 2**20


def _finish_item(item: Item, staged: dict[str, Path]) -> None:
    """Move/unpack verified files into place."""
    for f in item.files:
        if f.unpack:
            extract_flat(staged[f.name], config.MODELS_DIR / f.dest)
        else:
            target = config.MODELS_DIR / f.dest
            if staged[f.name] != target:
                os.replace(staged[f.name], target)
    if item.id == "cuda":
        _copy_vc_runtime(config.MODELS_DIR / "bin" / "llama-cuda")
    if item.marker:
        (config.MODELS_DIR / item.marker).write_text(_marker_text(item), encoding="utf-8")


def _copy_vc_runtime(target: Path) -> None:
    """The CUDA build needs the same VC++ runtime the app ships next to its bundled
    llama.cpp builds — reuse those (clean PCs may not have it installed)."""
    src = config.APP_BIN / "llama-vulkan"
    if not src.is_dir():
        return
    for dll in src.glob("*.dll"):
        if dll.name.lower().startswith(("vcruntime140", "msvcp140", "concrt140")):
            shutil.copy2(dll, target / dll.name)


def _checksum(f: FileSpec) -> str | None:
    if f.sha256 or not f.hf:
        return f.sha256
    return hf_meta(*f.hf)[0]


def install(ids: list[str], job=None, cancel: CancelToken | None = None) -> dict:
    items = [BY_ID[i] for i in ids if i in BY_ID]
    todo = [it for it in items if not is_installed(it)]
    prog = _Progress(job, [f for it in todo for f in it.files])
    cache = config.MODELS_DIR / "downloads"
    for it in todo:
        staged = {}
        for f in it.files:
            dest = (cache / f.name) if f.unpack else (config.MODELS_DIR / f.dest)
            download(f.url, dest, sha256=_checksum(f), size=f.size,
                     progress=prog.file(f, "Lade"), cancel=cancel)
            prog.finished(f)
            staged[f.name] = dest
        _finish_item(it, staged)
        for f in it.files:
            if f.unpack:
                staged[f.name].unlink(missing_ok=True)
    return {"installed": [it.id for it in todo], "skipped": [it.id for it in items
                                                            if it not in todo]}


def find_in_folder(folder: Path, name: str) -> Path | None:
    for p in folder.rglob(name):
        if p.is_file():
            return p
    return None


def import_folder(folder: Path, ids: list[str] | None = None, job=None,
                  cancel: CancelToken | None = None) -> dict:
    """Offline import (USB stick / network share): find catalog files by name,
    copy with verification. Missing files are reported, not fatal."""
    if not folder.is_dir():
        raise FileNotFoundError(f"Ordner nicht gefunden: {folder}")
    items = [it for it in CATALOG if (ids is None or it.id in ids) and not is_installed(it)]
    found: dict[str, dict[str, Path]] = {}
    missing: list[str] = []
    for it in items:
        paths = {f.name: find_in_folder(folder, f.name) for f in it.files}
        if all(paths.values()):
            found[it.id] = paths
        elif ids is not None:
            missing += [n for n, p in paths.items() if not p]
    files = [f for it in items if it.id in found for f in it.files]
    prog = _Progress(job, files)
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)  # fresh install: not there yet
    tmp = Path(tempfile.mkdtemp(dir=config.MODELS_DIR))
    imported = []
    try:
        for it in items:
            if it.id not in found:
                continue
            staged = {}
            for f in it.files:
                dest = (tmp / f.name) if f.unpack else (config.MODELS_DIR / f.dest)
                copy_verified(found[it.id][f.name], dest, f.sha256, f.size,
                              progress=prog.file(f, "Importiere"), cancel=cancel)
                prog.finished(f)
                staged[f.name] = dest
            _finish_item(it, staged)
            imported.append(it.id)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"imported": imported, "missing": missing,
            "unverified": [f.name for it in items if it.id in imported for f in it.files
                           if not f.sha256]}


def manifest() -> str:
    """What a model pack folder must contain (for preparing a USB stick)."""
    return json.dumps([{"item": it.id, "file": f.name, "size": f.size, "sha256": f.sha256,
                        "url": f.url} for it in CATALOG for f in it.files], indent=2)
