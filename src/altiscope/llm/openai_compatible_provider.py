"""Generate structured output through a compatible chat-completions endpoint.

Declared capabilities select the mode:
* native: pass the output schema to the SDK's parse method.
* json_mode: request a JSON object, include the schema in the prompt, and validate locally.
* prompt: include the schema in the prompt and validate locally.

In the latter two modes, strip code fences before validation. A completed response with
no parsed result is marked invalid_output. Expected output failures retain available
metadata. SDK transport retries are bounded and separate from output repair.
Compatibility depends on the endpoint.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, TypeVar

import httpx
import openai
from pydantic import BaseModel, ValidationError

from altiscope.llm.credentials import api_key as resolve_api_key
from altiscope.llm.provider import GenerationResult, Usage
from altiscope.llm.registry import ModelSpec, ProviderSpec
from altiscope.llm.tokens import estimate_tokens
from altiscope.llm.types import Effort

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)

_FINISH_TO_STOP: dict[str, str] = {
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "refusal",
}

# Map Altiscope effort settings to the three levels used by this adapter.
_EFFORT_MAP: dict[Effort, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.match(text)
    return match.group(1) if match else text.strip()


def _schema_instruction(output_type: type[BaseModel]) -> str:
    schema = json.dumps(output_type.model_json_schema(), indent=None, sort_keys=True)
    return (
        "\n\nRespond with a single JSON object and nothing else. It must conform to this "
        f"JSON schema:\n{schema}"
    )


class OpenAICompatibleProvider:
    def __init__(
        self,
        spec: ProviderSpec,
        client: openai.OpenAI | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.name = spec.name
        if client is not None:
            self._client = client
            return
        api_key = resolve_api_key(spec.api_key_env)
        self._client = openai.OpenAI(
            # Local servers need no key but the SDK insists on a string.
            api_key=api_key or "not-needed",
            base_url=spec.base_url,
            timeout=spec.timeout_seconds,
            http_client=http_client,
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
        try:
            return self._generate(
                model=model,
                system=system,
                user=user,
                output_type=output_type,
                max_tokens=max_tokens,
                effort=effort,
            )
        except (
            openai.LengthFinishReasonError,
            openai.ContentFilterFinishReasonError,
            ValidationError,
            openai.APIError,
        ) as exc:
            stop = "invalid_output"
            if isinstance(exc, openai.LengthFinishReasonError):
                stop = "max_tokens"
            elif isinstance(exc, openai.ContentFilterFinishReasonError):
                stop = "refusal"
            elif isinstance(exc, openai.APIError):
                stop = "transport_error"
            completion = getattr(exc, "completion", None)
            usage = getattr(completion, "usage", None)
            return GenerationResult(
                parsed=None,
                raw_text="",
                model_id=model.wire_name,
                stop_reason=stop,
                usage=Usage(
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                ),
                latency_ms=int((time.monotonic() - started) * 1000),
                output_mode=model.structured_output_mode,
                provider_request_id=getattr(exc, "request_id", None),
                validation_error=type(exc).__name__,
            )

    def _generate(
        self,
        *,
        model: ModelSpec,
        system: str,
        user: str,
        output_type: type[T],
        max_tokens: int,
        effort: Effort,
    ) -> GenerationResult[T]:
        mode = model.structured_output_mode
        kwargs: dict[str, Any] = {}
        if "reasoning_effort" in model.capabilities:
            kwargs["reasoning_effort"] = _EFFORT_MAP[effort]
            # OpenAI reasoning models reject max_tokens in favour of this parameter.
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

        started = time.monotonic()
        if mode == "native":
            raw_response = self._client.chat.completions.with_raw_response.parse(
                model=model.wire_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=output_type,
                **kwargs,
            )
            try:
                completion = raw_response.parse()
            except (
                ValidationError,
                openai.LengthFinishReasonError,
                openai.ContentFilterFinishReasonError,
            ) as exc:
                payload = raw_response.http_response.json()
                usage = payload.get("usage") or {}
                choice_data = (payload.get("choices") or [{}])[0]
                message = choice_data.get("message") or {}
                stop = _FINISH_TO_STOP.get(choice_data.get("finish_reason") or "", "invalid_output")
                if stop == "end_turn":
                    stop = "invalid_output"
                return GenerationResult(
                    parsed=None,
                    raw_text=message.get("content") or "",
                    model_id=payload.get("model") or model.wire_name,
                    stop_reason=stop,
                    usage=Usage(
                        usage.get("prompt_tokens", 0),
                        usage.get("completion_tokens", 0),
                        (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                    ),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    output_mode=mode,
                    provider_request_id=raw_response.headers.get("x-request-id"),
                    validation_error=type(exc).__name__,
                )
            choice = completion.choices[0]
            parsed: T | None = choice.message.parsed
            raw_text = choice.message.content or ""
            validation_error: str | None = None
        else:
            if mode == "json_mode":
                kwargs["response_format"] = {"type": "json_object"}
            completion = self._client.chat.completions.create(
                model=model.wire_name,
                messages=[
                    {"role": "system", "content": system + _schema_instruction(output_type)},
                    {"role": "user", "content": user},
                ],
                **kwargs,
            )
            choice = completion.choices[0]
            raw_text = choice.message.content or ""
            parsed, validation_error = None, None
            try:
                parsed = output_type.model_validate_json(_strip_fences(raw_text))
            except ValidationError as exc:
                validation_error = str(exc)
        latency_ms = int((time.monotonic() - started) * 1000)

        stop_reason = _FINISH_TO_STOP.get(choice.finish_reason or "", "unknown")
        refusal = getattr(choice.message, "refusal", None)
        if refusal:
            stop_reason = "refusal"
        if stop_reason == "end_turn" and parsed is None:
            stop_reason = "invalid_output"
        if stop_reason != "end_turn":
            parsed = None

        usage_obj = completion.usage
        cached = 0
        if usage_obj is not None and usage_obj.prompt_tokens_details is not None:
            cached = usage_obj.prompt_tokens_details.cached_tokens or 0
        usage = Usage(
            input_tokens=usage_obj.prompt_tokens if usage_obj else 0,
            output_tokens=usage_obj.completion_tokens if usage_obj else 0,
            cache_read_tokens=cached,
        )
        return GenerationResult(
            parsed=parsed,
            raw_text=raw_text,
            model_id=completion.model or model.wire_name,
            stop_reason=stop_reason,
            usage=usage,
            latency_ms=latency_ms,
            output_mode=mode,
            provider_request_id=getattr(completion, "_request_id", None),
            refusal_category="content_filter" if stop_reason == "refusal" else None,
            validation_error=validation_error,
        )

    def count_tokens(self, *, model: ModelSpec, system: str, user: str) -> int:
        # This adapter estimates the supplied text without an endpoint token count.
        return estimate_tokens(system) + estimate_tokens(user)
