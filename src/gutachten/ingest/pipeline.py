# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ingest: hash incoming files, dedupe, render pages at fixed DPI.

Every physical page gets a stable `global_seq` — that is the citation number
"Bl. N d.A." used everywhere downstream (timeline, findings, export).

Pages are rendered to temporary files *before* touching the database, so the
write transaction that assigns `global_seq` is short and never blocks OCR
running concurrently on the same case.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import imagehash
import pymupdf as fitz
from PIL import Image, ImageSequence

from .. import config
from ..cases import IMAGE_SUFFIXES, PDF_SUFFIXES, case_db_path
from ..db import database
from . import convert

MIN_EMBEDDED_CHARS = 40  # below this a "text layer" is treated as absent
# A page whose raster images cover more than this share is a scan: its text layer
# (scanner OCR, Eingangsstempel, fax header) is not trusted as the page content.
MAX_IMAGE_COVERAGE_FOR_TEXT = 0.5


def trust_text_layer(embedded_chars: int, image_coverage: float) -> bool:
    return embedded_chars >= MIN_EMBEDDED_CHARS and image_coverage < MAX_IMAGE_COVERAGE_FOR_TEXT

_case_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _case_lock(case_id: str) -> threading.Lock:
    """Serializes seq assignment per case (concurrent uploads)."""
    with _locks_guard:
        return _case_locks.setdefault(case_id, threading.Lock())


@dataclass
class _RenderedPage:
    page_no: int
    tmp_path: Path
    width: int
    height: int
    phash: str
    embedded_chars: int
    image_coverage: float


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _inbox_name(inbox: Path, src: Path, digest: str, keep_name: bool) -> str:
    """Stored filename inside inbox/. Never reuses a name held by different content."""
    hashed = f"{digest[:12]}{src.suffix.lower()}"
    if not keep_name:
        return hashed
    dest = inbox / src.name
    if not dest.exists() or _sha256(dest) == digest:
        return src.name
    return f"{src.stem}-{digest[:12]}{src.suffix}"  # same name, different file


def import_file(case_id: str, src: Path, keep_name: bool = True,
                orig_name: str | None = None, _depth: int = 0) -> dict:
    """Copy a file into inbox/, register it in sources, render pages. Non-PDF/image
    files go through an import module (convert.py) that produces a text PDF."""
    orig_name = orig_name or src.name
    if convert.ignored(orig_name):
        return {"status": "skipped", "reason": "Systemdatei", "pages_added": 0}
    tmpdir = Path(tempfile.mkdtemp(prefix="gutachten-conv-"))
    try:
        return _import(case_id, src, keep_name, orig_name, tmpdir, _depth)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _import(case_id: str, src: Path, keep_name: bool, orig_name: str, tmpdir: Path,
            depth: int) -> dict:
    cdir = config.case_dir(case_id)
    db_path = case_db_path(case_id)
    suffix = src.suffix.lower()
    digest = _sha256(src)
    converted: Path | None = None
    attachments: list[tuple[str, bytes]] = []
    how = None
    if suffix not in PDF_SUFFIXES | IMAGE_SUFFIXES:
        converted, attachments, how = convert.to_pdf(src, orig_name, tmpdir)

    dup = _find_duplicate(db_path, case_id, digest)
    if dup:
        return _record_duplicate(db_path, case_id, src, digest, dup)

    # Render outside the DB transaction (slow part).
    pages_dir = cdir / "pages"
    pages_dir.mkdir(exist_ok=True)
    try:
        rendered = (_render_pdf(converted, pages_dir) if converted
                    else _render_pdf(src, pages_dir) if suffix in PDF_SUFFIXES
                    else _render_image(src, pages_dir))
    except Exception as e:
        _record_error(db_path, case_id, src, digest, str(e))
        return {"status": "error", "reason": f"could not read file: {e}", "pages_added": 0}

    try:
        with _case_lock(case_id):
            dup = _find_duplicate(db_path, case_id, digest)  # raced with a twin upload?
            if dup:
                return _record_duplicate(db_path, case_id, src, digest, dup)

            inbox = cdir / "inbox"
            inbox.mkdir(exist_ok=True)
            dest = inbox / _inbox_name(inbox, src, digest, keep_name)
            if not dest.exists():
                shutil.copy2(src, dest)

            conn = database.connect(db_path)
            try:
                cur = conn.execute(
                    "INSERT INTO sources (case_id, kind, filename, orig_name, sha256, bytes)"
                    " VALUES (?, 'scan', ?, ?, ?, ?)",
                    (case_id, dest.name, orig_name, digest, src.stat().st_size),
                )
                source_id = cur.lastrowid
                seq = conn.execute(
                    "SELECT COALESCE(MAX(global_seq), 0) FROM pages WHERE case_id=?",
                    (case_id,),
                ).fetchone()[0]
                final_paths: list[Path] = []
                for rp in rendered:
                    seq += 1
                    rel = f"pages/P{seq:04d}.png"
                    conn.execute(
                        """INSERT INTO pages
                           (case_id, source_id, page_no, global_seq, image_path,
                            width, height, phash, has_embedded_text,
                            embedded_chars, image_coverage)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (case_id, source_id, rp.page_no, seq, rel, rp.width, rp.height,
                         rp.phash,
                         int(trust_text_layer(rp.embedded_chars, rp.image_coverage)),
                         rp.embedded_chars, rp.image_coverage),
                    )
                    final_paths.append(cdir / rel)
                database.audit(conn, case_id, "ingest_file",
                               f"{orig_name}: {len(rendered)} pages"
                               + (f" (umgewandelt: {how})" if how else ""))
                for rp, final in zip(rendered, final_paths, strict=True):
                    rp.tmp_path.replace(final)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        result = {"status": "ingested", "source_id": source_id,
                  "pages_added": len(rendered), "converted": how}
    finally:
        for rp in rendered:
            rp.tmp_path.unlink(missing_ok=True)
    if attachments and depth < 2:
        result["attachments"] = []
        for i, (name, data) in enumerate(attachments):
            att = tmpdir / f"att{i}" / name
            att.parent.mkdir()
            att.write_bytes(data)
            r = import_file(case_id, att, keep_name=True, orig_name=name, _depth=depth + 1)
            result["attachments"].append({"filename": name, **r})
            result["pages_added"] += r.get("pages_added", 0)
    return result


def _find_duplicate(db_path: Path, case_id: str, digest: str):
    conn = database.connect(db_path)
    try:
        return conn.execute(
            "SELECT id, filename FROM sources"
            " WHERE case_id=? AND sha256=? AND status='ingested'",
            (case_id, digest),
        ).fetchone()
    finally:
        conn.close()


def _record_duplicate(db_path: Path, case_id: str, src: Path, digest: str, dup) -> dict:
    conn = database.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sources (case_id, kind, filename, orig_name,"
            " sha256, bytes, status, duplicate_of)"
            " VALUES (?, 'scan', ?, ?, ?, ?, 'duplicate', ?)",
            (case_id, dup["filename"], src.name, digest, src.stat().st_size, dup["id"]),
        )
        database.audit(conn, case_id, "ingest_duplicate", f"{src.name} = {dup['filename']}")
        conn.commit()
    finally:
        conn.close()
    return {"status": "duplicate", "duplicate_of": dup["filename"], "pages_added": 0}


def _record_error(db_path: Path, case_id: str, src: Path, digest: str, err: str) -> None:
    conn = database.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO sources (case_id, kind, filename, orig_name, sha256, bytes, status)"
            " VALUES (?, 'scan', ?, ?, ?, ?, 'error')",
            (case_id, src.name, src.name, digest, src.stat().st_size),
        )
        database.audit(conn, case_id, "ingest_error", f"{src.name}: {err}")
        conn.commit()
    finally:
        conn.close()


def _save_tmp(
    img: Image.Image, pages_dir: Path, page_no: int, embedded: int, coverage: float
) -> _RenderedPage:
    tmp = pages_dir / f".tmp-{uuid.uuid4().hex}.png"
    img.save(tmp, format="PNG", optimize=True)
    return _RenderedPage(page_no, tmp, img.width, img.height,
                         str(imagehash.phash(img)), embedded, coverage)


def image_coverage(page: fitz.Page) -> float:
    """Share of the page covered by raster images, rasterized on a coarse grid
    so overlapping images are not double-counted."""
    rect = page.rect
    if rect.is_empty:
        return 0.0
    n = 50
    grid = [[False] * n for _ in range(n)]
    for info in page.get_image_info():
        b = fitz.Rect(info["bbox"]) & rect
        if b.is_empty:
            continue
        c0 = int((b.x0 - rect.x0) / rect.width * n)
        c1 = int((b.x1 - rect.x0) / rect.width * n + 0.999)
        r0 = int((b.y0 - rect.y0) / rect.height * n)
        r1 = int((b.y1 - rect.y0) / rect.height * n + 0.999)
        for r in range(max(r0, 0), min(r1, n)):
            row = grid[r]
            for c in range(max(c0, 0), min(c1, n)):
                row[c] = True
    return sum(map(sum, grid)) / (n * n)


def _render_pdf(pdf_path: Path, pages_dir: Path) -> list[_RenderedPage]:
    out: list[_RenderedPage] = []
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                embedded = len(page.get_text("text").strip())
                pix = page.get_pixmap(dpi=config.RENDER_DPI)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                out.append(_save_tmp(img, pages_dir, page.number + 1, embedded,
                                     image_coverage(page)))
    except Exception:
        for rp in out:
            rp.tmp_path.unlink(missing_ok=True)
        raise
    return out


def _render_image(img_path: Path, pages_dir: Path) -> list[_RenderedPage]:
    """One page per frame — multi-page TIFFs are common scanner output."""
    out: list[_RenderedPage] = []
    try:
        with Image.open(img_path) as im:
            for i, frame in enumerate(ImageSequence.Iterator(im), start=1):
                out.append(_save_tmp(frame.convert("RGB"), pages_dir, i, 0, 1.0))
    except Exception:
        for rp in out:
            rp.tmp_path.unlink(missing_ok=True)
        raise
    return out
