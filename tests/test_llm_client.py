# SPDX-License-Identifier: AGPL-3.0-or-later
import json

import httpx
import pytest

from gutachten.llm.client import LlamaClient, LlmError


def _client(content, finish="stop"):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen35-9b-q4"}]})
        seen["payload"] = json.loads(req.read())
        return httpx.Response(200, json={"choices": [
            {"message": {"content": content}, "finish_reason": finish}]})

    return LlamaClient(transport=httpx.MockTransport(handler)), seen


def test_chat_json_disables_thinking_and_sends_schema():
    c, seen = _client('{"ok": true}')
    assert c.chat_json([{"role": "user", "content": "x"}], {"type": "object"}) == {"ok": True}
    p = seen["payload"]
    assert p["chat_template_kwargs"] == {"enable_thinking": False}
    assert p["response_format"]["json_schema"]["strict"] is True
    assert c.model_id == "qwen35-9b-q4"


@pytest.mark.parametrize("content,finish,msg", [
    ("", "stop", "empty"),
    ('{"facts": [', "length", "truncated"),
    ("not json", "stop", "invalid JSON"),
])
def test_chat_json_failures_raise_llm_error(content, finish, msg):
    c, _ = _client(content, finish)
    with pytest.raises(LlmError, match=msg):
        c.chat_json([{"role": "user", "content": "x"}], {"type": "object"})
