# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenAI-compatible client for a local llama-server.

Anything with `model_id` and `chat_json(...)` satisfies `JsonLLM`, so the
analysis pipeline can run against a scripted fake in tests.
"""
from __future__ import annotations

import json
from typing import Protocol

import httpx

from .. import config


class LlmError(RuntimeError):
    pass


class JsonLLM(Protocol):
    model_id: str

    def chat_json(
        self, messages: list[dict], schema: dict, schema_name: str = "response",
        max_tokens: int = 4096,
    ) -> dict: ...


class LlamaClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 600.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url or f"http://{config.LLAMA_HOST}:{config.LLAMA_PORT}/v1"
        self.timeout = timeout
        self._transport = transport
        self._model_id: str | None = None

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(timeout=timeout or self.timeout, transport=self._transport)

    @property
    def model_id(self) -> str:
        """Name of the loaded model as reported by llama-server (for provenance)."""
        if self._model_id is None:
            try:
                with self._client(10) as http:
                    data = http.get(f"{self.base_url}/models").json().get("data") or []
                self._model_id = data[0]["id"] if data else "unknown"
            except Exception:
                return "unknown"
        return self._model_id

    def _post(self, payload: dict) -> dict:
        with self._client() as http:
            r = http.post(f"{self.base_url}/chat/completions", json=payload)
            r.raise_for_status()
        return r.json()["choices"][0]

    def chat_text(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        choice = self._post({
            "model": "local",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        return choice["message"]["content"]

    def chat_json(
        self,
        messages: list[dict],
        schema: dict,
        schema_name: str = "response",
        max_tokens: int = 4096,
    ) -> dict:
        """Constrained decoding — llama.cpp enforces the JSON schema."""
        payload = {
            "model": "local",
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
            # Thinking mode (Qwen, Gemma) + grammar-constrained output yields empty
            # answers; extraction doesn't need it.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        choice = self._post(payload)
        content = (choice.get("message") or {}).get("content") or ""
        if not content.strip():
            raise LlmError(f"empty response ({schema_name})")
        if choice.get("finish_reason") == "length":
            raise LlmError(f"response truncated at max_tokens ({schema_name})")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LlmError(f"invalid JSON ({schema_name}): {e}") from None

    def healthy(self) -> bool:
        try:
            with self._client(5) as http:
                return http.get(f"{self.base_url}/models").status_code == 200
        except Exception:
            return False
