# SPDX-License-Identifier: AGPL-3.0-or-later
"""Desktop launcher: backend + app window (the entry point of DerGutachter.exe).

  - starts the FastAPI backend in-process on 127.0.0.1 (free port if 8077 is taken)
  - opens a native window (pywebview -> Edge WebView2 on Windows 11, WKWebView on
    macOS); falls back to the default browser if no webview is available
  - one instance per user: a second start just opens a window on the running one
  - closing the window stops the backend and the llama-server child process

    uv run python -m gutachten.desktop          # dev: same as the installed app
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import unquote

import httpx

from . import config

log = logging.getLogger("gutachten.desktop")
TITLE = "Der Gutachter"


def _setup_logging() -> Path:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.LOGS_DIR / "app.log"
    # Windowed apps have no console: sys.stdout/stderr are None and uvicorn's
    # default handlers would crash on first write.
    if sys.stdout is None or sys.stderr is None:
        stream = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()],
    )
    return path


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((config.API_HOST, port))
            return True
        except OSError:
            return False


def _free_port() -> int:
    if _port_free(config.API_PORT):
        return config.API_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((config.API_HOST, 0))
        return s.getsockname()[1]


def _healthy(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------- single instance

LOCK_FILE = config.user_data_dir() / "instance.json"


def running_instance() -> str | None:
    """URL of an already running instance of this user, if any."""
    try:
        info = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = info.get("url")
    return url if url and _healthy(url) else None


def _write_lock(url: str) -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")


def _clear_lock() -> None:
    try:
        if json.loads(LOCK_FILE.read_text(encoding="utf-8")).get("pid") == os.getpid():
            LOCK_FILE.unlink()
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- backend

class Backend:
    def __init__(self, port: int):
        import uvicorn

        from .api.app import create_app

        self.url = f"http://{config.API_HOST}:{port}"
        self.server = uvicorn.Server(uvicorn.Config(
            create_app(), host=config.API_HOST, port=port,
            log_config=None,  # use our logging (file), not uvicorn's console config
        ))
        self.thread = threading.Thread(target=self.server.run, name="backend", daemon=True)

    def start(self, timeout: float = 30) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _healthy(self.url):
                return
            if not self.thread.is_alive():
                raise RuntimeError("Backend konnte nicht starten — siehe logs/app.log")
            time.sleep(0.1)
        raise TimeoutError("Backend antwortet nicht")

    def stop(self) -> None:
        from .llm.server import server as llama

        llama.stop()
        self.server.should_exit = True
        self.thread.join(timeout=10)


# ---------------------------------------------------------------- window

BUNDLE_SUFFIXES = {".dll", ".pyd", ".exe"}


def unblock_bundle(root: Path | None = None) -> int:
    """Remove the Windows "Mark of the Web" from our own program files.

    A portable ZIP downloaded from the internet and extracted with Explorer marks
    every file as coming from the internet (NTFS stream Zone.Identifier). .NET
    Framework then refuses to load pythonnet's Python.Runtime.dll and the window
    fails ("Failed to resolve Python.Runtime.Loader.Initialize"). Only our own
    bundle is touched, only that stream is removed; nothing else changes.
    """
    if os.name != "nt" or not config.FROZEN:
        return 0
    root = root or config.APP_DIR
    n = 0
    for p in root.rglob("*"):
        if p.suffix.lower() not in BUNDLE_SUFFIXES:
            continue
        try:
            os.remove(f"{p}:Zone.Identifier")
            n += 1
        except OSError:
            pass  # no mark (normal for the installer) or read-only location
    if n:
        log.info("Internet-Markierung von %d Programmdateien entfernt", n)
    return n


def _filename(resp: httpx.Response, fallback: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=utf-8''([^;]+)", cd, re.I) or re.search(
        r'filename="?([^";]+)"?', cd, re.I)
    return unquote(m.group(1)) if m else fallback


def save_download(base_url: str, path: str, webview_mod, target_dir: Path | None = None
                  ) -> str | None:
    if not path.startswith("/api/"):
        raise ValueError("nur Dateien der lokalen App")
    resp = httpx.get(base_url.rstrip("/") + path, timeout=300)
    resp.raise_for_status()
    name = _filename(resp, Path(path).name)
    folder = target_dir or Path.home() / "Downloads"
    if webview_mod is not None:
        res = webview_mod.windows[0].create_file_dialog(
            webview_mod.SAVE_DIALOG, directory=str(folder), save_filename=name)
        if not res:
            return None
        dest = Path(res if isinstance(res, str) else res[0])
    else:
        dest = folder / name
    dest.write_bytes(resp.content)
    log.info("Datei gespeichert: %s (%d Bytes)", dest, len(resp.content))
    return str(dest)


def open_window(url: str) -> None:
    """Native window; blocks until it is closed. Falls back to the browser."""
    try:
        import webview  # pywebview
    except ImportError:
        log.warning("pywebview not installed — opening the default browser")
        webbrowser.open(url)
        _wait_forever()
        return
    class JsApi:
        """Native helpers callable from the UI (window.pywebview.api.*)."""

        def pick_folder(self) -> str | None:
            res = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            return res[0] if res else None

        def save_download(self, path: str) -> str | None:
            """Word export, protocol CSV …: the embedded browser does not deliver
            downloads, so the file is fetched from the local backend and saved via
            the system's save dialog. -> saved path, or None if cancelled."""
            return save_download(url, path, webview)

    settings = getattr(webview, "settings", None)
    if isinstance(settings, dict):
        settings["ALLOW_DOWNLOADS"] = True  # off by default in pywebview
    try:
        webview.create_window(TITLE, url, width=1440, height=920, min_size=(1024, 700),
                              js_api=JsApi())
        webview.start()
    except Exception:  # noqa: BLE001 — e.g. WebView2/.NET unavailable: keep working
        log.exception("native window failed — opening the default browser instead")
        webbrowser.open(url)
        _wait_forever()


def _wait_forever() -> None:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def smoke_test(out: Path) -> int:
    """Headless self-test of an installed/built app (CI has no screen): backend,
    bundled binaries, and import + OCR of a generated scan through the full stack."""
    import subprocess
    import tempfile

    import pymupdf as fitz

    res: dict = {"frozen": config.FROZEN, "app_dir": str(config.APP_DIR)}
    ok = True
    backend = Backend(_free_port())
    try:
        backend.start()
        res["backend"] = _healthy(backend.url)
        ui = httpx.get(backend.url + "/", timeout=10)
        res["ui"] = ui.status_code == 200 and 'id="root"' in ui.text
        from .ocr.tesseract_engine import TesseractEngine

        res["tesseract"] = {"cmd": config.tesseract_cmd(), "version": TesseractEngine().version(),
                            "tessdata": str(config.TESSDATA_DIR),
                            "deu": (config.TESSDATA_DIR / "deu.traineddata").exists()}
        llama = config.llama_server_bin()
        ver = subprocess.run([llama, "--version"], capture_output=True, text=True, timeout=60,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        res["llama_server"] = {"bin": llama, "version": (ver.stdout + ver.stderr).strip()[-120:]}

        from .cases import create_case
        from .ingest.pipeline import import_file
        from .ocr.runner import ocr_pending_pages

        tmp = Path(tempfile.mkdtemp())
        src = fitz.open()
        pg = src.new_page(width=595, height=842)
        pg.insert_textbox(fitz.Rect(60, 60, 540, 400),
                          "Röntgen Knie links: mediale Gonarthrose Grad II.", fontsize=14)
        png = pg.get_pixmap(dpi=200).tobytes("png")
        scan = fitz.open()
        scan.new_page(width=595, height=842).insert_image(fitz.Rect(0, 0, 595, 842), stream=png)
        scan.save(tmp / "scan.pdf")
        cid = create_case("Smoke-Test")
        import_file(cid, tmp / "scan.pdf")
        res["ocr"] = ocr_pending_pages(cid)
        r = httpx.get(f"{backend.url}/api/cases/{cid}/pages/1", timeout=10).json()
        text = r.get("text_md") or ""
        res["ocr_text"] = text[:80]
        ok = res["backend"] and res["ui"] and "Gonarthrose" in text
        if config.FROZEN and config.IS_WINDOWS:
            # the .NET bridge of the window (pythonnet) must load — also from a portable
            # ZIP that Windows marked as "from the internet" (CI sets that mark)
            try:
                import clr  # noqa: F401

                res["dotnet_bridge"] = True
            except Exception as e:  # noqa: BLE001
                res["dotnet_bridge"] = repr(e)
        if config.FROZEN and config.IS_WINDOWS:  # the Windows bundle must be self-contained
            ok = ok and res.get("dotnet_bridge") is True and res["tesseract"]["deu"] \
                and "Röntgen" in text \
                and str(config.APP_BIN) in (config.tesseract_cmd() or "") \
                and str(config.APP_BIN) in (llama or "")
    except Exception as e:  # report, don't crash: CI reads the file
        log.exception("smoke test failed")
        res["error"] = repr(e)
        ok = False
    finally:
        backend.stop()
    res["ok"] = ok
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


def main() -> None:
    unblock_bundle()
    if "--smoke-test" in sys.argv:
        _setup_logging()
        i = sys.argv.index("--smoke-test")
        out = Path(sys.argv[i + 1]) if len(sys.argv) > i + 1 else Path("smoke.json")
        raise SystemExit(smoke_test(out))
    logpath = _setup_logging()
    log.info("start: frozen=%s app_dir=%s data=%s models=%s",
             config.FROZEN, config.APP_DIR, config.DATA_HOME, config.MODELS_DIR)
    if url := running_instance():
        log.info("instance already running at %s — opening a window on it", url)
        open_window(url)
        return
    from .llm.server import reap_orphans
    from .llm.server import server as llama

    reap_orphans()  # memory still held by a model of a crashed earlier session
    backend = Backend(_free_port())
    try:
        backend.start()
    except Exception:
        log.exception("backend start failed (log: %s)", logpath)
        raise
    _write_lock(backend.url)
    log.info("backend at %s", backend.url)
    _guard_model_memory(llama)
    try:
        open_window(backend.url)
    finally:
        log.info("window closed — shutting down")
        _clear_lock()
        backend.stop()


def _guard_model_memory(llama) -> None:
    """The language model holds several GB. It is stopped when the app ends — also on
    a termination signal — and unloaded while the app stays open but no evaluation
    used it for 20 minutes (it reloads automatically on the next evaluation)."""
    import atexit
    import signal

    from .api.jobs import jobs
    from .llm.server import IDLE_UNLOAD_S

    atexit.register(llama.stop)

    def _on_signal(signum, _frame):
        log.info("signal %s — stopping the language model", signum)
        llama.stop()
        raise SystemExit(0)

    for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            try:
                signal.signal(sig, _on_signal)
            except (ValueError, OSError):
                pass  # not in the main thread / not supported here

    def _idle_watch():
        while True:
            time.sleep(60)
            if llama.owns_running() and not jobs.active() \
                    and llama.idle_seconds() > IDLE_UNLOAD_S:
                log.info("Sprachmodell %d min unbenutzt — entladen (Speicher frei)",
                         IDLE_UNLOAD_S // 60)
                llama.stop()

    threading.Thread(target=_idle_watch, daemon=True, name="model-idle").start()


if __name__ == "__main__":
    main()
