# SPDX-License-Identifier: AGPL-3.0-or-later
"""OCR engine protocol and result types."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class OcrBlock:
    text: str
    x0: float = 0.0  # normalized 0..1 coordinates
    y0: float = 0.0
    x1: float = 1.0
    y1: float = 1.0
    confidence: float | None = None
    block_type: str = "line"


@dataclass
class OcrResult:
    text: str
    blocks: list[OcrBlock] = field(default_factory=list)
    confidence: float = 0.0  # 0..1 page-level
    engine: str = "unknown"
    engine_version: str = ""
    model_id: str | None = None
    rotation: int = 0  # degrees the image was rotated before OCR


class OcrEngine(Protocol):
    """OCR over a rendered page image; may need the original source file."""

    name: str

    def version(self) -> str: ...
    def ocr_image(self, image_path: Path) -> OcrResult: ...
    def ocr_page(self, page: dict, case_dir: Path) -> OcrResult: ...
