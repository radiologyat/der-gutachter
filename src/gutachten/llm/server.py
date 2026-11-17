# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manage a local llama-server process.

Stages run sequentially, so a single loaded model at a time keeps us inside the
8 GB VRAM budget: the OCR VLM is swapped out for the text LLM between stages.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

import httpx

from .. import config

log = logging.getLogger("gutachten.llm.server")


IDLE_UNLOAD_S = 20 * 60  # free the memory when no model call happened for 20 minutes


def _ours(p) -> bool:
    """A llama-server started by this app (our port and our models folder)."""
    try:
        name = (p.info.get("name") or "").lower()
        cmd = " ".join(p.info.get("cmdline") or [])
    except Exception:  # noqa: BLE001
        return False
    return ("llama-server" in name and f"--port {config.LLAMA_PORT}" in cmd
            and str(config.MODELS_DIR) in cmd)


def reap_orphans(keep_pid: int | None = None) -> int:
    """Stop language-model processes left behind by an earlier session (crash, killed
    app): they hold several GB of memory until the computer restarts. Only processes
    of this app are touched (our port and models folder)."""
    import psutil

    n = 0
    for p in psutil.process_iter(["name", "cmdline"]):
        if p.pid == keep_pid or not _ours(p):
            continue
        try:
            p.terminate()
            try:
                p.wait(10)
            except psutil.TimeoutExpired:
                p.kill()
            n += 1
        except psutil.Error:
            pass
    if n:
        log.info("liegengebliebene Sprachmodell-Prozesse beendet: %d", n)
    return n


def _kill_with_parent(proc: subprocess.Popen):
    """Windows: tie the model process to this app (job object with
    KILL_ON_JOB_CLOSE) so it ends with the app — also on a crash or when the app is
    ended in the Task Manager. Returns the job handle, which must stay open."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        if not k32.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle)):
            log.warning("AssignProcessToJobObject fehlgeschlagen (%s)",
                        ctypes.get_last_error())
        return job
    except Exception:  # noqa: BLE001 — never block the model start
        log.exception("Job-Objekt für llama-server nicht angelegt")
        return None


class LlamaServer:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.loaded_model: Path | None = None
        self._job = None
        self.last_used = time.time()
        self.log_path: Path | None = None
        self.binary: str | None = None

    def touch(self) -> None:
        self.last_used = time.time()

    def owns_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def idle_seconds(self) -> float:
        return time.time() - self.last_used

    @property
    def health_url(self) -> str:
        return f"http://{config.LLAMA_HOST}:{config.LLAMA_PORT}/health"

    def running(self) -> bool:
        try:
            return httpx.get(self.health_url, timeout=2).status_code == 200
        except Exception:
            return False

    def start(
        self,
        model_path: Path,
        alias: str = "local",
        ctx: int = 32768,
        n_gpu_layers: int = 999,  # llama.cpp splits what doesn't fit onto CPU
        extra_args: list[str] | None = None,
        timeout_s: int = 180,
    ) -> None:
        if self.running() and self.loaded_model == model_path:
            return
        self.stop()
        binaries = config.llama_server_bins()
        if not binaries:
            raise FileNotFoundError(
                "llama-server nicht gefunden — scripts/download_models.py ausführen"
                " oder LLAMA_SERVER_BIN setzen"
            )
        # Best build first (CUDA > Vulkan > CPU). A build that cannot start on this
        # machine (missing GPU driver, unsupported CPU) falls through to the next one.
        errors = []
        for binary in binaries:
            try:
                self._start_one(binary, model_path, alias, ctx, n_gpu_layers,
                                extra_args, timeout_s)
                self.binary = binary
                return
            except RuntimeError as e:
                errors.append(f"{binary}: {e}")
        raise RuntimeError("Kein llama-server-Build startete:\n" + "\n".join(errors))

    def backend_info(self) -> dict | None:
        """Which build runs and where the model layers ended up (from the server log
        of the current start): CUDA / Vulkan / CPU / Metal, device, offloaded layers."""
        binary = getattr(self, "binary", None)
        if not binary or not self.running():
            return None
        folder = Path(binary).parent.name.lower()
        build = next((b for b in ("cuda", "vulkan", "cpu") if b in folder), None)
        text = ""
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
            text = text[text.rfind("=== start"):]
        except (OSError, AttributeError):
            pass
        dev = re.search(r"(?:using device|ggml_\w+_init: found \d+ \w+ devices?:?\s*\n?\s*"
                        r"Device \d+:)\s*([^\n]+)", text)
        off = re.search(r"offloaded (\d+)/(\d+) layers to GPU", text)
        if build is None:
            build = "metal" if "Metal" in text else ("cuda" if "CUDA" in text else
                                                     "vulkan" if "Vulkan" in text else "cpu")
        info = {"build": build, "binary": binary,
                "device": dev.group(1).strip()[:120] if dev else None,
                "gpu_layers": f"{off.group(1)}/{off.group(2)}" if off else None}
        info["on_gpu"] = bool(off and int(off.group(1)) > 0)
        return info

    def _start_one(self, binary, model_path, alias, ctx, n_gpu_layers, extra_args,
                   timeout_s) -> None:
        cmd = [
            binary,
            "--model", str(model_path),
            "--alias", alias,
            "--host", config.LLAMA_HOST,
            "--port", str(config.LLAMA_PORT),
            "--ctx-size", str(ctx),
            "--n-gpu-layers", str(n_gpu_layers),
            "--jinja",
            *(extra_args or []),
        ]
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = config.LOGS_DIR / "llama-server.log"
        log = self.log_path.open("ab")
        log.write(f"\n=== start {binary}\n".encode())
        log.flush()
        self.proc = subprocess.Popen(
            cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            # no console window popping up per model start on Windows
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log.close()  # the child keeps its own handle
        self._job = _kill_with_parent(self.proc)
        self.touch()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self.proc = None
                raise RuntimeError("exited during startup — " + _tail(self.log_path, 5))
            if self.running():
                self.loaded_model = model_path
                return
            time.sleep(0.5)
        self.stop()
        raise TimeoutError(f"llama-server did not become healthy in {timeout_s}s")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.loaded_model = None
        self._job = None


def _tail(path: Path, n: int = 15) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


server = LlamaServer()
