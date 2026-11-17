# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared plumbing for the analysis stages: model acquisition and LLM-call logging."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from .. import config
from ..llm.client import JsonLLM, LlamaClient, LlmError
from ..llm.prompts import SYSTEM

Progress = Callable[[str, int, int], None]  # step, done, total


class LlmUnavailable(RuntimeError):
    pass


def _extract_model_path() -> Path | None:
    if config.EXTRACT_MODEL:
        p = Path(config.EXTRACT_MODEL)
        return p if p.exists() else None
    if config.EXTRACT_MODEL_DIR.exists():
        ggufs = sorted(config.EXTRACT_MODEL_DIR.glob("*.gguf"))
        ggufs = [g for g in ggufs if "mmproj" not in g.name]
        return ggufs[0] if ggufs else None
    return None


def get_llm() -> JsonLLM:
    """Use a running llama-server, else start one with the extraction model."""
    from ..llm.server import reap_orphans, server

    client = LlamaClient()
    if client.healthy():
        if server.owns_running():
            return client
        # a model server of an earlier session (left behind by a crash): it would never
        # be stopped and keep its memory — replace it by our own
        if not reap_orphans():
            return client  # someone else's server (development setup): use it
    model = _extract_model_path()
    if model is None:
        raise LlmUnavailable(
            "Sprachmodell Gemma 4 12B nicht gefunden. Bitte unter Einrichtung "
            "herunterladen (ca. 7 GB) oder aus einem Ordner importieren."
        )
    try:
        server.start(model, ctx=config.EXTRACT_CTX)
    except (FileNotFoundError, RuntimeError, TimeoutError) as e:
        raise LlmUnavailable(f"llama-server konnte nicht starten: {e}") from None
    return client


# case_id -> the model call in progress (shown as "KI arbeitet an … seit … s", so a
# long call is not mistaken for a hang)
_ACTIVE: dict[str, dict] = {}


def active_call(case_id: str) -> dict | None:
    return _ACTIVE.get(case_id)


def call_llm(
    conn: sqlite3.Connection,
    case_id: str,
    llm: JsonLLM,
    *,
    stage: str,
    ref: str,
    prompt_version: str,
    prompt: str,
    schema: dict,
    max_tokens: int = 4096,
) -> dict:
    """Run one structured LLM call and log it in llm_calls (also on failure).

    An identical earlier request (same stage, prompt version, model and prompt) is
    answered from the stored result — that makes every step resumable after a crash
    or after closing the app, and a rerun with unchanged input costs nothing."""
    h = hashlib.sha256("\x1f".join((stage, prompt_version, llm.model_id or "", prompt,
                                    json.dumps(schema, sort_keys=True))).encode()).hexdigest()
    row = conn.execute(
        "SELECT output_json FROM llm_calls WHERE case_id=? AND prompt_hash=? AND "
        "status='ok' AND output_json IS NOT NULL ORDER BY id DESC LIMIT 1",
        (case_id, h)).fetchone()
    if row:
        conn.execute(
            "INSERT INTO llm_calls (case_id, stage, ref, prompt_version, model_id,"
            " output_json, status, duration_ms, prompt_hash) VALUES (?,?,?,?,?,?,'cache',0,?)",
            (case_id, stage, ref, prompt_version, llm.model_id, row[0], h))
        conn.commit()  # never keep a write transaction open into the next (long) call
        return json.loads(row[0])
    t0 = time.monotonic()
    _ACTIVE[case_id] = {"stage": stage, "ref": ref, "since": time.time()}
    from ..llm.server import server as _srv

    _srv.touch()
    try:
        out = llm.chat_json(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            schema=schema, schema_name=stage, max_tokens=max_tokens,
        )
    except Exception as e:
        conn.execute(
            "INSERT INTO llm_calls (case_id, stage, ref, prompt_version, model_id,"
            " status, error, duration_ms, prompt_hash) VALUES (?,?,?,?,?,'error',?,?,?)",
            (case_id, stage, ref, prompt_version, llm.model_id, str(e),
             int((time.monotonic() - t0) * 1000), h),
        )
        conn.commit()
        _ACTIVE.pop(case_id, None)
        raise LlmError(str(e)) from e
    _ACTIVE.pop(case_id, None)
    conn.execute(
        "INSERT INTO llm_calls (case_id, stage, ref, prompt_version, model_id,"
        " output_json, duration_ms, prompt_hash) VALUES (?,?,?,?,?,?,?,?)",
        (case_id, stage, ref, prompt_version, llm.model_id,
         json.dumps(out, ensure_ascii=False), int((time.monotonic() - t0) * 1000), h),
    )
    conn.commit()  # stored at once: an interruption loses at most the call in progress
    return out


def page_texts(conn: sqlite3.Connection, case_id: str) -> list[dict]:
    return [
        dict(r) for r in conn.execute(
            """SELECT p.id, p.global_seq, p.source_id, p.status,
                      COALESCE(pt.text_md, '') AS text
               FROM pages p LEFT JOIN page_text pt ON pt.page_id = p.id
               WHERE p.case_id=? ORDER BY p.global_seq""",
            (case_id,),
        )
    ]
