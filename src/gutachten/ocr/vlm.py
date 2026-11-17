# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vision-language-model OCR via llama.cpp's OpenAI-compatible endpoint.

Used for PaddleOCR-VL / dots.ocr GGUF weights (models/ dir). The whole page is
returned as one block — VLMs give excellent text but unreliable boxes; for
citation highlighting we fall back to full-page citation.

Confidence: VLMs report no per-word confidence, so we derive one from the
token log-probabilities llama-server returns (`logprobs: true`) and then
penalize the typical VLM failure modes — empty output, truncation at
max_tokens, and repetition loops. Those pages go to the review queue.
"""
from __future__ import annotations

import base64
import math
from pathlib import Path

import httpx

from .. import config
from .base import OcrBlock, OcrResult

OCR_PROMPT_VERSION = "vlm-ocr-v2"
OCR_PROMPT = (
    "OCR this scanned document page faithfully. "
    "Output the text in Markdown, preserving reading order, headings, lists and "
    "tables. Keep German umlauts. Do not add commentary."
)
MAX_TOKENS = 4096

# Used when the server returns no logprobs: plausible output passes review,
# anything suspicious is capped below the threshold by the penalties.
FALLBACK_CONFIDENCE = 0.8
SUSPECT_CAP = 0.3  # empty / truncated / looping output
MIN_CHARS = 20


def repetition_ratio(text: str) -> float:
    """Share of non-trivial lines that are repeats — VLMs that lose track of the
    page tend to emit the same line over and over."""
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 3]
    if len(lines) < 6:
        return 0.0
    return 1 - len(set(lines)) / len(lines)


def score_output(text: str, finish_reason: str | None, logprobs: list[float] | None) -> float:
    if logprobs:
        # geometric-mean token probability
        conf = math.exp(sum(logprobs) / len(logprobs))
    else:
        conf = FALLBACK_CONFIDENCE
    if (
        len(text.strip()) < MIN_CHARS
        or finish_reason == "length"
        or repetition_ratio(text) > 0.5
    ):
        conf = min(conf, SUSPECT_CAP)
    return round(conf, 4)


class VlmEngine:
    """Calls a running llama-server hosting a multimodal GGUF model."""

    def __init__(
        self,
        model_id: str,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.model_id = model_id
        self.base_url = base_url or f"http://{config.LLAMA_HOST}:{config.LLAMA_PORT}/v1"
        self.name = f"vlm:{model_id}"
        self.prompt_version = OCR_PROMPT_VERSION
        self._transport = transport  # tests inject a mock

    def version(self) -> str:
        return self.model_id

    def ocr_image(self, image_path: Path) -> OcrResult:
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        payload = {
            "model": self.model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": OCR_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": MAX_TOKENS,
            "logprobs": True,
        }
        with httpx.Client(timeout=300, transport=self._transport) as http:
            r = http.post(f"{self.base_url}/chat/completions", json=payload)
            r.raise_for_status()
        choice = r.json()["choices"][0]
        text = (choice["message"].get("content") or "").strip()
        lp_content = (choice.get("logprobs") or {}).get("content") or []
        logprobs = [t["logprob"] for t in lp_content if t.get("logprob") is not None]
        conf = score_output(text, choice.get("finish_reason"), logprobs or None)
        return OcrResult(
            text=text,
            blocks=[OcrBlock(text=text, confidence=conf, block_type="paragraph")],
            confidence=conf,
            engine=self.name,
            engine_version=self.model_id,
            model_id=self.model_id,
        )

    def ocr_page(self, page: dict, case_dir: Path) -> OcrResult:
        return self.ocr_image(case_dir / page["image_path"])
