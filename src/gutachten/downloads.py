# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resumable, checksum-verified downloads (models, llama.cpp runtime).

Used by the in-app setup screen. Network access happens ONLY through these
functions, and only when the user explicitly starts a download.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import httpx

Progress = Callable[[int, int | None], None]  # bytes done, bytes total


class CancelToken(Protocol):
    def is_set(self) -> bool: ...


class Cancelled(Exception):
    pass


class ChecksumError(Exception):
    pass


def sha256_file(path: Path, cancel: CancelToken | None = None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            h.update(chunk)
    return h.hexdigest()


def _client(timeout_read: float = 300) -> httpx.Client:
    return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=timeout_read))


def download(
    url: str,
    dest: Path,
    sha256: str | None = None,
    size: int | None = None,
    progress: Progress | None = None,
    cancel: CancelToken | None = None,
) -> bool:
    """Download url to dest via dest.part, resuming a previous partial download.
    Verifies SHA-256 if given. Returns False if dest was already complete."""
    if dest.exists() and (
        (sha256 and sha256_file(dest, cancel) == sha256)
        or (not sha256 and size and dest.stat().st_size == size)
    ):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with _client() as http, http.stream("GET", url, headers=headers) as r:
        if r.status_code != 416:  # 416: .part already complete
            r.raise_for_status()
            if have and r.status_code != 206:  # server ignored Range: start over
                have = 0
            total = size or ((int(r.headers.get("content-length", 0)) + have) or None)
            done = have
            with part.open("ab" if have else "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()  # .part stays: next attempt resumes
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
    verify_and_move(part, dest, sha256, size, cancel)
    return True


def verify_and_move(part: Path, dest: Path, sha256: str | None, size: int | None,
                    cancel: CancelToken | None = None) -> None:
    if size and part.stat().st_size != size:
        got = part.stat().st_size
        part.unlink()
        raise ChecksumError(f"{dest.name}: Grösse {got} statt {size} Bytes")
    if sha256:
        got = sha256_file(part, cancel)
        if got != sha256:
            part.unlink()
            raise ChecksumError(
                f"{dest.name}: SHA-256 stimmt nicht ({got[:12]}… ≠ {sha256[:12]}…)")
    os.replace(part, dest)


def copy_verified(src: Path, dest: Path, sha256: str | None, size: int | None,
                  progress: Progress | None = None, cancel: CancelToken | None = None) -> None:
    """Copy a local file (offline import, e.g. from a USB stick) with verification."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    total = src.stat().st_size
    done = 0
    with src.open("rb") as fi, part.open("wb") as fo:
        for chunk in iter(lambda: fi.read(8 << 20), b""):
            if cancel is not None and cancel.is_set():
                fo.close()
                part.unlink(missing_ok=True)
                raise Cancelled()
            fo.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    verify_and_move(part, dest, sha256, size, cancel)


def hf_meta(repo: str, filename: str) -> tuple[str | None, int | None]:
    """(sha256, size) of a file in a Hugging Face model repo (from its LFS pointer)."""
    with _client(60) as http:
        r = http.get(f"https://huggingface.co/api/models/{repo}/tree/main")
        r.raise_for_status()
    for e in r.json():
        if e.get("path") == filename:
            lfs = e.get("lfs") or {}
            return lfs.get("oid"), lfs.get("size") or e.get("size")
    raise FileNotFoundError(f"{filename} not found in {repo}")


def hf_url(repo: str, filename: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{filename}"


def extract_flat(zip_path: Path, target: Path) -> None:
    """Unpack all files of a zip into one folder (llama.cpp DLLs must sit next to the exe)."""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for m in zf.infolist():
            if not m.is_dir():
                with zf.open(m) as s, (target / Path(m.filename).name).open("wb") as d:
                    shutil.copyfileobj(s, d)
