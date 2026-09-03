"""Exercise the chat-completions adapter against a fake server (httpx MockTransport)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel, ConfigDict

from altiscope.llm.openai_compatible_provider import OpenAICompatibleProvider
from altiscope.llm.providers import build_provider
from altiscope.llm.registry import ModelSpec, ProviderSpec


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    count: int


def _completion(content: str, finish: str = "stop", refusal: str | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if refusal:
        message["refusal"] = refusal
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "served-name",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
            "prompt_tokens_details": {"cached_tokens": 4},
        },
    }


class FakeServer:
    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.requests: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        return httpx.Response(200, json=self.reply)


def _provider(server: FakeServer) -> OpenAICompatibleProvider:
    spec = ProviderSpec(name="local", kind="openai_compatible", base_url="http://fake/v1")
    client = openai.OpenAI(
        api_key="x",
        base_url="http://fake/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(server.handler)),
    )
    return OpenAICompatibleProvider(spec, client=client)


def _model(*caps: str) -> ModelSpec:
    return ModelSpec(
        id="m",
        provider="local",
        model_name="wire-name",
        display_name="M",
        context_window=100_000,
        max_output_tokens=8_000,
        capabilities=set(caps),  # type: ignore[arg-type]
    )


def test_native_mode_sends_json_schema_and_parses():
    server = FakeServer(_completion('{"headline": "h", "count": 3}'))
    result = _provider(server).generate_structured(
        model=_model("json_schema"),
        system="sys",
        user="usr",
        output_type=Out,
        max_tokens=1000,
        effort="high",
    )
    assert result.ok and result.parsed == Out(headline="h", count=3)
    assert result.output_mode == "native"
    assert result.usage.input_tokens == 11 and result.usage.cache_read_tokens == 4
    assert result.model_id == "served-name"
    req = server.requests[0]
    assert req["model"] == "wire-name"
    assert req["response_format"]["type"] == "json_schema"
    assert req["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert req["max_tokens"] == 1000 and "reasoning_effort" not in req


def test_reasoning_effort_and_max_completion_tokens_when_supported():
    server = FakeServer(_completion('{"headline": "h", "count": 1}'))
    _provider(server).generate_structured(
        model=_model("json_schema", "reasoning_effort"),
        system="s",
        user="u",
        output_type=Out,
        max_tokens=500,
        effort="xhigh",
    )
    req = server.requests[0]
    assert req["reasoning_effort"] == "high"
    assert req["max_completion_tokens"] == 500 and "max_tokens" not in req


def test_json_mode_prompts_schema_and_validates():
    server = FakeServer(_completion('{"headline": "h", "count": 2}'))
    result = _provider(server).generate_structured(
        model=_model("json_mode"),
        system="sys",
        user="usr",
        output_type=Out,
        max_tokens=100,
        effort="low",
    )
    assert result.ok and result.parsed is not None and result.parsed.count == 2
    assert result.output_mode == "json_mode"
    req = server.requests[0]
    assert req["response_format"] == {"type": "json_object"}
    assert "JSON schema" in req["messages"][0]["content"]
    assert '"headline"' in req["messages"][0]["content"]


def test_prompt_mode_strips_fences():
    server = FakeServer(_completion('```json\n{"headline": "h", "count": 9}\n```'))
    result = _provider(server).generate_structured(
        model=_model(),
        system="s",
        user="u",
        output_type=Out,
        max_tokens=100,
        effort="low",
    )
    assert result.ok and result.parsed is not None and result.parsed.count == 9
    assert result.output_mode == "prompt"
    assert "response_format" not in server.requests[0]


def test_invalid_output_is_reported_not_raised():
    server = FakeServer(_completion('{"headline": "h", "count": "many"}'))
    result = _provider(server).generate_structured(
        model=_model("json_mode"),
        system="s",
        user="u",
        output_type=Out,
        max_tokens=100,
        effort="low",
    )
    assert not result.ok and result.parsed is None
    assert result.stop_reason == "invalid_output"
    assert result.validation_error and "count" in result.validation_error


def test_truncation_and_refusal_map_to_stop_reasons():
    truncated = FakeServer(_completion('{"headline": "h", "count": 1}', finish="length"))
    r1 = _provider(truncated).generate_structured(
        model=_model("json_mode"),
        system="s",
        user="u",
        output_type=Out,
        max_tokens=5,
        effort="low",
    )
    assert r1.stop_reason == "max_tokens" and r1.parsed is None

    refused = FakeServer(_completion("", refusal="no"))
    r2 = _provider(refused).generate_structured(
        model=_model("json_mode"),
        system="s",
        user="u",
        output_type=Out,
        max_tokens=5,
        effort="low",
    )
    assert r2.stop_reason == "refusal" and r2.refusal_category == "content_filter"


def test_count_tokens_is_an_overestimate_without_an_endpoint():
    server = FakeServer(_completion("{}"))
    n = _provider(server).count_tokens(model=_model(), system="a" * 300, user="b" * 300)
    assert n == 200
    assert server.requests == []


def test_factory_builds_unauthenticated_local_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = build_provider(
        ProviderSpec(name="ollama", kind="openai_compatible", base_url="http://localhost:11434/v1")
    )
    assert isinstance(p, OpenAICompatibleProvider) and p.name == "ollama"


def test_factory_builds_anthropic_provider(monkeypatch: pytest.MonkeyPatch):
    from altiscope.llm.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    p = build_provider(
        ProviderSpec(name="anthropic", kind="anthropic", api_key_env="ANTHROPIC_API_KEY")
    )
    assert isinstance(p, AnthropicProvider) and p.name == "anthropic"
