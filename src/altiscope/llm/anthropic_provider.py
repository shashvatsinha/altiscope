"""Generate structured output and count tokens through the Anthropic SDK.

Uses adaptive thinking and the requested effort level. Cloud-specific SDK clients are
not wired into provider construction yet.
"""

from __future__ import annotations

import os
import time
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from altiscope.llm.provider import GenerationResult, Usage
from altiscope.llm.registry import ModelSpec, ProviderSpec
from altiscope.llm.tokens import estimate_tokens
from altiscope.llm.types import Effort

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider:
    def __init__(self, spec: ProviderSpec, client: anthropic.Anthropic | None = None) -> None:
        self.name = spec.name
        if client is not None:
            self._client = client
            return
        api_key = os.environ.get(spec.api_key_env) if spec.api_key_env else None
        # With api_key=None the SDK resolves ANTHROPIC_API_KEY or an auth profile itself.
        self._client = anthropic.Anthropic(
            api_key=api_key, base_url=spec.base_url, timeout=spec.timeout_seconds
        )

    def generate_structured(
        self,
        *,
        model: ModelSpec,
        system: str,
        user: str,
        output_type: type[T],
        max_tokens: int,
        effort: Effort,
    ) -> GenerationResult[T]:
        started = time.monotonic()
        response = self._client.messages.parse(
            model=model.wire_name,
            max_tokens=max_tokens,
            # The system prompt is stable per prompt version; cache it. The user turn
            # (the PR material) varies per call and follows the breakpoint.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=output_type,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
        )
        latency_ms = int((time.monotonic() - started) * 1000)

        refusal_category: str | None = None
        if response.stop_reason == "refusal" and response.stop_details is not None:
            refusal_category = getattr(response.stop_details, "category", None)

        raw_text = "".join(
            block.text for block in response.content if isinstance(block, anthropic.types.TextBlock)
        )
        parsed: T | None = response.parsed_output if response.stop_reason == "end_turn" else None
        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_input_tokens or 0,
            cache_write_tokens=response.usage.cache_creation_input_tokens or 0,
        )
        return GenerationResult(
            parsed=parsed,
            raw_text=raw_text,
            model_id=response.model,
            stop_reason=response.stop_reason or "unknown",
            usage=usage,
            latency_ms=latency_ms,
            output_mode="native",
            provider_request_id=response._request_id,  # pyright: ignore[reportPrivateUsage]
            refusal_category=refusal_category,
        )

    def count_tokens(self, *, model: ModelSpec, system: str, user: str) -> int:
        if "token_counting" not in model.capabilities:
            return estimate_tokens(system) + estimate_tokens(user)
        result = self._client.messages.count_tokens(
            model=model.wire_name,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return result.input_tokens
