from pathlib import Path
from typing import Any

import anthropic
import httpx2 as httpx
import pytest

from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.providers import ProviderPool
from altiscope.llm.registry import Registry
from altiscope.prompts import latest_prompt
from altiscope.summarize.generate import generate_account
from altiscope.summarize.service import prepare
from tests.conftest import REPO_ROOT


def test_direct_anthropic_review_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot: PullRequestSnapshot
):
    registry = Registry.load(REPO_ROOT / "config/examples/anthropic.yaml")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=test-direct-key\n")
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "msg-direct",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": '{"review":"The patch adds a lock."}'}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 9},
            },
        )

    client_type = anthropic.Anthropic

    def client(**kwargs: Any):
        return client_type(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        )

    monkeypatch.setattr(anthropic, "Anthropic", client)
    model = registry.models[registry.stages["pr_summary"].candidates[0]]
    pool = ProviderPool(registry)
    provider = pool.for_model(model.id)
    generated = generate_account(
        prepare(snapshot),
        provider,
        model,
        system=latest_prompt(REPO_ROOT / "prompts", "pr_summary").body,
        max_tokens=4096,
        effort="low",
        input_budget=100000,
    )
    assert provider.name == "anthropic"
    assert pool.for_model(model.id) is provider
    assert generated.publication.output
    assert generated.publication.output.review == "The patch adds a lock."
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.anthropic.com/v1/messages"
    assert requests[0].headers["x-api-key"] == "test-direct-key"
    assert b'"model":"claude-sonnet-5"' in requests[0].content
    default = Registry.load(REPO_ROOT / "config/models.yaml")
    assert default.models[model.id] == model
