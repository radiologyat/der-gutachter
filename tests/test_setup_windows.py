# SPDX-License-Identifier: AGPL-3.0-or-later
"""Windows setup logic, testable on any OS (no network)."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from gutachten import config

_spec = importlib.util.spec_from_file_location(
    "download_models", Path(__file__).resolve().parents[1] / "scripts" / "download_models.py"
)
dm = importlib.util.module_from_spec(_spec)
sys.modules["download_models"] = dm  # @dataclass needs the module registered
_spec.loader.exec_module(dm)


@pytest.mark.parametrize("cuda,expected", [
    ((13, 5), ["llama-B-bin-win-cuda-13.5-x64.zip", "cudart-llama-bin-win-cuda-13.5-x64.zip"]),
    ((13, 7), ["llama-B-bin-win-cuda-13.5-x64.zip", "cudart-llama-bin-win-cuda-13.5-x64.zip"]),
    ((12, 4), ["llama-B-bin-win-vulkan-x64.zip"]),   # old driver: never the 12.4 build
    (None, ["llama-B-bin-win-cpu-x64.zip"]),          # no NVIDIA GPU
])
def test_windows_llama_variant_from_driver(cuda, expected):
    assert dm.pick_windows_assets(cuda, build="B") == expected


def test_nvidia_smi_parsing(monkeypatch):
    class R:
        stdout = "| NVIDIA-SMI 590.12   Driver Version: 590.12   CUDA Version: 13.6     |"

    monkeypatch.setattr(dm.subprocess, "run", lambda *a, **k: R())
    assert dm.nvidia_cuda_version() == (13, 6)

    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(dm.subprocess, "run", missing)
    assert dm.nvidia_cuda_version() is None


def test_llama_server_prefers_bundled_build(tmp_path, monkeypatch):
    monkeypatch.delenv("LLAMA_SERVER_BIN", raising=False)
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    exe = tmp_path / "bin" / "llama" / "llama-server.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert config.llama_server_bin() == str(exe)
    monkeypatch.setenv("LLAMA_SERVER_BIN", "C:/custom/llama-server.exe")
    assert config.llama_server_bin() == "C:/custom/llama-server.exe"


def test_tesseract_found_in_program_files_without_path(tmp_path, monkeypatch):
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    monkeypatch.setattr(config.shutil, "which", lambda _: None)
    exe = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert config.tesseract_cmd() == str(exe)


def test_missing_llama_server_gives_actionable_error(monkeypatch):
    from gutachten.llm.server import LlamaServer

    monkeypatch.setattr(config, "llama_server_bins", lambda: [])
    s = LlamaServer()
    monkeypatch.setattr(s, "running", lambda: False)
    with pytest.raises(FileNotFoundError, match="download_models"):
        s.start(Path("x.gguf"))


def test_resumable_download_and_checksum(tmp_path, monkeypatch):
    import hashlib

    import httpx

    data = os.urandom(300_000)
    seen = []

    def handler(req):
        rng = req.headers.get("range")
        seen.append(rng)
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        return httpx.Response(206 if rng else 200, content=data[start:])

    real_client = httpx.Client
    monkeypatch.setattr(dm.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(dm, "MODELS", tmp_path)
    dest = tmp_path / "gguf" / "m.gguf"
    dest.parent.mkdir()
    (dest.parent / "m.gguf.part").write_bytes(data[:100_000])  # interrupted earlier
    dm.download("https://x/m.gguf", dest, sha256=hashlib.sha256(data).hexdigest())
    assert dest.read_bytes() == data and seen == ["bytes=100000-"]

    bad = tmp_path / "gguf" / "bad.gguf"
    with pytest.raises(SystemExit, match="SHA-256 mismatch"):
        dm.download("https://x/bad.gguf", bad, sha256="0" * 64)
    assert not bad.exists() and not bad.with_name("bad.gguf.part").exists()


def test_windows_scripts_are_ascii_crlf():
    repo = Path(__file__).resolve().parents[1]
    for rel in ("scripts/setup_windows.ps1", "scripts/start_windows.bat",
                "packaging/signing/Zertifikat-vertrauen.ps1", "packaging/installer.iss"):
        name = rel
        raw = (repo / rel).read_bytes()
        raw.decode("ascii")  # PowerShell 5.1 misreads non-ASCII without BOM
        assert b"\n" not in raw.replace(b"\r\n", b""), f"{name} must use CRLF"


def test_server_falls_back_to_next_build(monkeypatch, tmp_path):
    """A build that exits at startup (e.g. no Vulkan driver) -> next candidate."""
    from gutachten.llm.server import LlamaServer

    monkeypatch.setattr(config, "llama_server_bins", lambda: ["vulkan.exe", "cpu.exe"])
    monkeypatch.setattr(config, "LOGS_DIR", tmp_path)
    s = LlamaServer()
    tried = []

    def fake_start(binary, *a):
        tried.append(binary)
        if binary == "vulkan.exe":
            raise RuntimeError("exited during startup")

    monkeypatch.setattr(s, "running", lambda: False)
    monkeypatch.setattr(s, "_start_one", fake_start)
    s.start(Path("m.gguf"))
    assert tried == ["vulkan.exe", "cpu.exe"] and s.binary == "cpu.exe"

    monkeypatch.setattr(config, "llama_server_bins", lambda: ["vulkan.exe"])
    with pytest.raises(RuntimeError, match="Kein llama-server-Build"):
        s.start(Path("m.gguf"))
