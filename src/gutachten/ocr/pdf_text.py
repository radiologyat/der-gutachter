# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extract the embedded text layer of a PDF page (born-digital documents)."""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from .base import OcrBlock, OcrResult


class PdfTextEngine:
    name = "pdf_text"

    def version(self) -> str:
        return fitz.VersionBind

    def ocr_image(self, image_path: Path) -> OcrResult:
        raise NotImplementedError("pdf_text needs the source PDF, not an image")

    def ocr_page(self, page: dict, case_dir: Path) -> OcrResult:
        src = case_dir / "inbox" / page["filename"]
        doc = fitz.open(src)
        try:
            p = doc[page["page_no"] - 1]
            rect = p.rect
            words = p.get_text("words")  # x0,y0,x1,y1,word,block,line,word_no
        finally:
            doc.close()

        lines: dict[tuple[int, int], list] = {}
        for w in words:
            lines.setdefault((w[5], w[6]), []).append(w)

        blocks: list[OcrBlock] = []
        out_lines: list[str] = []
        for _key, ws in sorted(lines.items()):
            ws.sort(key=lambda w: w[7])
            text = " ".join(w[4] for w in ws)
            x0 = min(w[0] for w in ws) / rect.width
            y0 = min(w[1] for w in ws) / rect.height
            x1 = max(w[2] for w in ws) / rect.width
            y1 = max(w[3] for w in ws) / rect.height
            blocks.append(
                OcrBlock(text=text, x0=x0, y0=y0, x1=x1, y1=y1, confidence=1.0)
            )
            out_lines.append(text)

        return OcrResult(
            text="\n".join(out_lines),
            blocks=blocks,
            confidence=1.0,
            engine=self.name,
            engine_version=self.version(),
        )
