# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app model setup: download/import with verification (no real network)."""
import hashlib
import io
import os
import threading
import zipfile

import httpx
import pytest

from gutachten import config
from gutachten import setup as S
from gutachten.downloads import Cancelled, ChecksumError


def _blob(n=200_000):
    return os.urandom(n)


def _corrupt(b: bytes) -> bytes:
    """Same size, guaranteed different (flipping a random byte to a constant can
    leave it unchanged 1 time in 256 — that made CI flaky)."""
    return b[:-1] + bytes([b[-1] ^ 0xFF])


@pytest.fixture()
def models(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    return tmp_path / "models"


def _catalog(monkeypatch, gguf: bytes, zips: dict[str, bytes]):
    """Small fake catalog: one model file + one 'cuda' item made of zips."""
    f_model = S.FileSpec(url="https://x/model.gguf", name="model.gguf", size=len(gguf),
                         sha256=hashlib.sha256(gguf).hexdigest(), dest="gguf/m/model.gguf")
    zfiles = tuple(
        S.FileSpec(url=f"https://x/{n}", name=n, size=len(b),
                   sha256=hashlib.sha256(b).hexdigest(), dest="bin/llama-cuda", unpack=True)
        for n, b in zips.items())
    cat = (S.Item(id="extract", label="M", description="", files=(f_model,), recommended=True),
           S.Item(id="cuda", label="C", description="", files=zfiles,
                  marker="bin/llama-cuda/.installed"))
    monkeypatch.setattr(S, "CATALOG", cat)
    monkeypatch.setattr(S, "BY_ID", {i.id: i for i in cat})


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in files.items():
            z.writestr(f"build/bin/{n}", b)
    return buf.getvalue()


def _serve(monkeypatch, blobs: dict[str, bytes], seen: list | None = None):
    def handler(req):
        name = req.url.path.rsplit("/", 1)[-1]
        data = blobs[name]
        rng = req.headers.get("range")
        if seen is not None:
            seen.append((name, rng))
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        return httpx.Response(206 if rng else 200, content=data[start:])

    real = httpx.Client
    monkeypatch.setattr("gutachten.downloads.httpx.Client",
                        lambda **kw: real(transport=httpx.MockTransport(handler)))


class Job:
    def __init__(self):
        self.total = self.done = 0
        self.step = None


def test_install_downloads_verifies_and_unpacks(models, monkeypatch):
    gguf = _blob()
    zips = {"llama.zip": _zip({"llama-server.exe": b"exe", "ggml.dll": b"dll"}),
            "cudart.zip": _zip({"cudart64.dll": b"rt"})}
    _catalog(monkeypatch, gguf, zips)
    _serve(monkeypatch, {"model.gguf": gguf, **zips})
    job = Job()
    res = S.install(["extract", "cuda"], job)
    assert res["installed"] == ["extract", "cuda"]
    assert (models / "gguf/m/model.gguf").read_bytes() == gguf
    assert sorted(p.name for p in (models / "bin/llama-cuda").iterdir()) == [
        ".installed", "cudart64.dll", "ggml.dll", "llama-server.exe"]
    assert not list((models / "downloads").glob("*.zip"))  # archives cleaned up
    assert job.done == job.total and all(S.is_installed(i) for i in S.CATALOG)
    assert S.install(["extract", "cuda"])["skipped"] == ["extract", "cuda"]


def test_corrupt_download_is_rejected(models, monkeypatch):
    gguf = _blob()
    _catalog(monkeypatch, gguf, {})
    _serve(monkeypatch, {"model.gguf": _corrupt(gguf)})  # same size, wrong content
    with pytest.raises(ChecksumError):
        S.install(["extract"])
    assert not (models / "gguf/m/model.gguf").exists()
    assert not (models / "gguf/m/model.gguf.part").exists()


def test_cancel_keeps_partial_and_resumes(models, monkeypatch):
    gguf = _blob(5 << 20)
    _catalog(monkeypatch, gguf, {})
    seen = []
    _serve(monkeypatch, {"model.gguf": gguf}, seen)
    stop = threading.Event()  # never set: second run completes
    job = Job()

    class StopAfterFirstMB:
        def is_set(self):
            return job.done >= 1

    with pytest.raises(Cancelled):
        S.install(["extract"], job, StopAfterFirstMB())
    part = models / "gguf/m/model.gguf.part"
    assert 0 < part.stat().st_size < len(gguf)
    S.install(["extract"], Job(), stop)
    assert (models / "gguf/m/model.gguf").read_bytes() == gguf
    assert seen[0][1] is None and seen[-1][1] is not None  # 2nd request resumed via Range


def test_offline_import_from_usb_folder(models, monkeypatch, tmp_path):
    gguf = _blob()
    zips = {"llama.zip": _zip({"llama-server.exe": b"exe"})}
    _catalog(monkeypatch, gguf, zips)
    usb = tmp_path / "USB" / "Modellpaket"
    (usb / "sub").mkdir(parents=True)
    (usb / "sub" / "model.gguf").write_bytes(gguf)
    (usb / "llama.zip").write_bytes(zips["llama.zip"])
    res = S.import_folder(usb)
    assert sorted(res["imported"]) == ["cuda", "extract"]
    assert (models / "bin/llama-cuda/llama-server.exe").read_bytes() == b"exe"
    assert all(S.is_installed(i) for i in S.CATALOG)


def test_offline_import_rejects_tampered_file(models, monkeypatch, tmp_path):
    gguf = _blob()
    _catalog(monkeypatch, gguf, {})
    usb = tmp_path / "usb"
    usb.mkdir()
    (usb / "model.gguf").write_bytes(_corrupt(gguf))
    with pytest.raises(ChecksumError):
        S.import_folder(usb)
    assert not S.is_installed(S.BY_ID["extract"])


def test_availability_rules(monkeypatch, models):
    info = {"ram_gb": 16.0, "gpu": None, "disk_free_gb": 500.0}
    cuda = S.BY_ID["cuda"]
    deep = S.Item(id="big", label="gross", description="", files=(), min_ram_gb=30)
    ok, why = S.availability(deep, info)
    assert not ok and "Arbeitsspeicher" in why
    assert S.availability(deep, {**info, "ram_gb": 32.0})[0]
    monkeypatch.setattr(config, "IS_WINDOWS", True)
    ok, why = S.availability(cuda, info)
    assert not ok and "Keine NVIDIA" in why
    old = {"name": "RTX 5070", "vram_gb": 8, "cuda": "12.4", "cuda_ok": False}
    ok, why = S.availability(cuda, {**info, "gpu": old})
    assert not ok and "Treiber" in why
    assert S.availability(cuda, {**info, "gpu": {**old, "cuda": "13.6", "cuda_ok": True}})[0]
    ok, why = S.availability(S.BY_ID["extract"], {**info, "disk_free_gb": 2.0})
    assert not ok and "Speicherplatz" in why


def test_setup_api_status_and_validation():
    from .test_api import client

    st = client.get("/api/setup/status").json()
    assert {i["id"] for i in st["items"]} == {"extract", "cuda"}
    assert "ram_gb" in st["system"] and st["job_id"] is None
    assert client.post("/api/setup/install", json={"items": ["nope"]}).status_code == 422
    assert client.post("/api/setup/import", json={"folder": "/does/not/exist"}).status_code == 400


def _claml(n=150):
    cls = "".join(
        f'<Class code="M{17 + i // 10}.{i % 10}" kind="category"><Rubric kind="preferred">'
        f"<Label>Testdiagnose {i}</Label></Rubric></Class>" for i in range(n))
    return (f'<?xml version="1.0"?><ClaML version="2.0.0"><Title name="ICD-10-GM" '
            f'version="2026">ICD-10-GM Testkatalog</Title>{cls}</ClaML>').encode()


def test_icd10_catalogue_import_enables_existence_check(models, tmp_path):
    from gutachten import icd10

    from .test_api import client

    assert icd10.exists("M17.1") is None  # no catalogue: unknown
    assert client.get("/api/setup/icd10").json()["imported"] is False
    bad = client.post("/api/setup/icd10", files={"file": ("x.xml", b"<ClaML/>")})
    assert bad.status_code == 400
    ok = client.post("/api/setup/icd10", files={"file": ("icd.xml", _claml())}).json()
    assert ok["codes"] == 150
    assert icd10.exists("M17.1") is True and icd10.exists("M99.9") is False
    assert icd10.search("Testdiagnose 1")[0]["code"].startswith("M")
    cid = client.post("/api/cases", json={"title": "ICD"}).json()["id"]
    r = client.post(f"/api/cases/{cid}/diagnoses", json={"text": "X", "icd10": "M99.9"})
    assert r.status_code == 422 and "nicht im ICD-10-GM-Katalog" in r.json()["detail"]
    assert client.post(f"/api/cases/{cid}/diagnoses",
                       json={"text": "Y", "icd10": "M17.1"}).status_code == 200
