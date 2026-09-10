from __future__ import annotations

import json

import anthropic
import httpx2 as httpx
import pytest
from pydantic import BaseModel, ConfigDict

from altiscope.llm.anthropic_provider import AnthropicProvider
from altiscope.llm.registry import ModelSpec, ProviderSpec


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


@pytest.mark.parametrize(
    ("text", "stop", "expected"),
    [
        ('{"text":"ok"}', "end_turn", "end_turn"),
        ('{"text":42}', "end_turn", "invalid_output"),
        ("not JSON", "end_turn", "invalid_output"),
        ("{}", "end_turn", "invalid_output"),
        ('{"text":"ok","sk-secret":"secret"}', "end_turn", "invalid_output"),
        ("not JSON", "pause_turn", "pause_turn"),
        ('{"text":', "max_tokens", "max_tokens"),
        ("refused", "refusal", "refusal"),
    ],
)
def test_anthropic_outcomes(text: str, stop: str, expected: str):
    requests: list[dict[str, object]] = []

    def handle(request: httpx.Request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"request-id": "req-fixture"},
            json={
                "id": "msg-1",
                "type": "message",
                "role": "assistant",
                "model": "served-model",
                "content": [{"type": "text", "text": text}],
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 9},
            },
        )

    client = anthropic.Anthropic(
        api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    provider = AnthropicProvider(ProviderSpec(name="anthropic", kind="anthropic"), client=client)
    model = ModelSpec(
        id="m",
        provider="anthropic",
        display_name="M",
        context_window=10000,
        max_output_tokens=1000,
        capabilities={"json_schema"},
    )
    result = provider.generate_structured(
        model=model, system="s", user="u", output_type=Output, max_tokens=500, effort="low"
    )
    assert result.stop_reason == expected
    assert result.ok == (expected == "end_turn")
    assert result.usage.input_tokens == 12 and result.usage.output_tokens == 9
    assert result.provider_request_id == "req-fixture"
    assert result.raw_text == text
    assert len(requests) == 1

    if expected == "invalid_output":
        assert result.validation_error
        assert "secret" not in result.validation_error
        assert any(
            code in result.validation_error
            for code in ("string_type", "json_invalid", "missing", "extra_forbidden")
        )
