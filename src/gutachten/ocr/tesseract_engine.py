# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tesseract OCR — CPU baseline, works offline everywhere.

German traineddata is expected under models/tessdata (see scripts/download_models.sh).
Falls back to the system tessdata dir when ours is missing a language.
"""
from __future__ import annotations

import functools
import io
import re
import subprocess
from pathlib import Path

from PIL import Image

from .. import config
from .base import OcrBlock, OcrResult

LANG = "deu+eng"

def _tessdata_dir() -> Path | None:
    if (config.TESSDATA_DIR / "deu.traineddata").exists():
        return config.TESSDATA_DIR
    return None


def run_tesseract(img: Image.Image, args: list[str], timeout: int = 300) -> str:
    """Run the Tesseract CLI on an image without any file path in the arguments.

    Tesseract on Windows reads paths with spaces or umlauts incorrectly, and the old
    pytesseract wrapper split its config at spaces — a user name like "Vorname
    Nachname" or "Bühler" in the install path broke the text recognition. So: the
    image goes in via stdin, the result comes out via stdout, and the tessdata folder
    is given relative to the working directory."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    d = _tessdata_dir()
    cmd = [config.tesseract_cmd() or "tesseract", "stdin", "stdout",
           *(["--tessdata-dir", d.name] if d else []), *args]
    r = subprocess.run(cmd, input=buf.getvalue(), capture_output=True, timeout=timeout,
                       cwd=str(d.parent) if d else None,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError("Tesseract: " + r.stderr.decode("utf-8", "replace").strip()[-300:])
    return r.stdout.decode("utf-8", "replace")


def _tsv(text: str) -> dict[str, list]:
    rows = [ln.split("\t") for ln in text.splitlines() if ln.strip()]
    if not rows:
        return {}
    head, body = rows[0], [r for r in rows[1:] if len(r) == len(rows[0])]
    data: dict[str, list] = {h: [] for h in head}
    for r in body:
        for h, v in zip(head, r, strict=True):
            data[h].append(v)
    for h in ("block_num", "par_num", "line_num", "left", "top", "width", "height"):
        data[h] = [int(x) for x in data.get(h, [])]
    data["conf"] = [float(x) for x in data.get("conf", [])]
    return data


@functools.cache
def tesseract_version() -> str:
    r = subprocess.run([config.tesseract_cmd() or "tesseract", "--version"],
                       capture_output=True, timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (r.stdout + r.stderr).decode("utf-8", "replace")
    m = re.search(r"tesseract v?(\S+)", out, re.I)
    return m.group(1) if m else out.strip()[:40]


class TesseractEngine:
    name = "tesseract"

    def version(self) -> str:
        return tesseract_version()

    def detect_rotation(self, image_path: Path) -> int:
        """Return degrees the image must be rotated to be upright (0/90/180/270)."""
        try:
            img = Image.open(image_path)
            img.thumbnail((1200, 1200))
            m = re.search(r"Rotate:\s*(\d+)", run_tesseract(img, ["--psm", "0"], 120))
            rot = int(m.group(1)) if m else 0
            return rot if rot in (0, 90, 180, 270) else 0
        except Exception:
            return 0

    def ocr_image(self, image_path: Path) -> OcrResult:
        img = Image.open(image_path)
        w, h = img.size
        data = _tsv(run_tesseract(img, ["-l", LANG, "-c", "tessedit_create_tsv=1",
                                        "-c", "tessedit_create_txt=0"]))

        lines: dict[tuple[int, int, int], list[int]] = {}
        n = len(data.get("text", []))
        for i in range(n):
            if not data["text"][i].strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(i)

        blocks: list[OcrBlock] = []
        out_lines: list[str] = []
        confs: list[float] = []
        for _key, idxs in sorted(lines.items()):
            text = " ".join(data["text"][i] for i in idxs)
            x0 = min(data["left"][i] for i in idxs) / w
            y0 = min(data["top"][i] for i in idxs) / h
            x1 = max(data["left"][i] + data["width"][i] for i in idxs) / w
            y1 = max(data["top"][i] + data["height"][i] for i in idxs) / h
            c = [data["conf"][i] for i in idxs if data["conf"][i] >= 0]
            conf = sum(c) / len(c) / 100 if c else 0.0
            confs.append(conf)
            blocks.append(
                OcrBlock(text=text, x0=x0, y0=y0, x1=x1, y1=y1, confidence=conf)
            )
            out_lines.append(text)

        page_conf = sum(confs) / len(confs) if confs else 0.0
        return OcrResult(
            text="\n".join(out_lines),
            blocks=blocks,
            confidence=page_conf,
            engine=self.name,
            engine_version=self.version(),
        )

    def ocr_page(self, page: dict, case_dir: Path) -> OcrResult:
        return self.ocr_image(case_dir / page["image_path"])


def cli_available() -> bool:
    cmd = config.tesseract_cmd()
    if not cmd:
        return False
    try:
        subprocess.run([cmd, "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False
