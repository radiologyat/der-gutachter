# SPDX-License-Identifier: AGPL-3.0-or-later
"""VLM OCR confidence — no real model needed (mocked llama-server)."""
import math

import httpx
from PIL import Image

from gutachten import config
from gutachten.ocr.vlm import VlmEngine, repetition_ratio, score_output

GOOD = "Arztbrief\nPatient: Max Muster\nDiagnose: Gonarthrose links\nMit freundlichen Grüssen"


def _engine(content, finish="stop", logprobs=None):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read()
        choice = {"message": {"content": content}, "finish_reason": finish}
        if logprobs is not None:
            choice["logprobs"] = {"content": [{"token": "x", "logprob": lp} for lp in logprobs]}
        return httpx.Response(200, json={"choices": [choice]})

    return VlmEngine("paddleocr-vl", transport=httpx.MockTransport(handler)), seen


def _img(tmp_path):
    p = tmp_path / "p.png"
    Image.new("RGB", (50, 50), "white").save(p)
    return p


def test_confidence_from_logprobs(tmp_path):
    eng, seen = _engine(GOOD, logprobs=[math.log(0.9)] * 10)
    r = eng.ocr_image(_img(tmp_path))
    assert abs(r.confidence - 0.9) < 1e-3
    assert b'"logprobs":true' in seen["body"].replace(b" ", b"")


def test_uncertain_model_goes_to_review(tmp_path):
    eng, _ = _engine(GOOD, logprobs=[math.log(0.5)] * 10)
    assert eng.ocr_image(_img(tmp_path)).confidence < config.OCR_REVIEW_THRESHOLD


def test_truncated_output_flagged(tmp_path):
    eng, _ = _engine(GOOD, finish="length", logprobs=[math.log(0.99)] * 10)
    assert eng.ocr_image(_img(tmp_path)).confidence < config.OCR_REVIEW_THRESHOLD


def test_empty_output_flagged(tmp_path):
    eng, _ = _engine("")
    assert eng.ocr_image(_img(tmp_path)).confidence < config.OCR_REVIEW_THRESHOLD


def test_repetition_loop_flagged():
    loop = "Diagnose: Gonarthrose\n" * 30
    assert repetition_ratio(loop) > 0.9
    assert score_output(loop, "stop", None) < config.OCR_REVIEW_THRESHOLD
    assert repetition_ratio(GOOD) == 0.0


def test_no_logprobs_plausible_output_passes():
    assert score_output(GOOD, "stop", None) >= config.OCR_REVIEW_THRESHOLD
