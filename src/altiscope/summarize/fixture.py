"""Recorded response adapter for the credential-free demo, never used for live input."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from altiscope.llm.provider import GenerationResult, Usage
from altiscope.llm.registry import ModelSpec, Registry
from altiscope.llm.tokens import estimate_tokens
from altiscope.llm.types import Effort
from altiscope.llm.validation import validation_diagnostic

T = TypeVar("T", bound=BaseModel)


class FixtureProvider:
    name = "fixture"

    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls = 0

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
        self.calls += 1
        raw = next(self.responses)
        diagnostic = None
        try:
            parsed = output_type.model_validate_json(raw)
        except ValidationError as exc:
            parsed = None
            diagnostic = validation_diagnostic(exc, output_type)
        return GenerationResult(
            parsed=parsed,
            validation_error=diagnostic,
            raw_text=raw,
            model_id="fixture",
            stop_reason="end_turn" if parsed is not None else "invalid_output",
            usage=Usage(0, 0),
            latency_ms=0,
            output_mode="native",
        )

    def count_tokens(self, *, model: ModelSpec, system: str, user: str) -> int:
        return estimate_tokens(system) + estimate_tokens(user)


def fixture_registry() -> Registry:
    return Registry.model_validate(
        {
            "providers": {"fixture": {"kind": "openai_compatible"}},
            "models": {
                "fixture": {
                    "provider": "fixture",
                    "display_name": "Recorded fixture",
                    "context_window": 200000,
                    "max_output_tokens": 4096,
                    "capabilities": ["json_schema"],
                }
            },
            "stages": {
                stage: {"candidates": ["fixture"], "effort": "low", "reserved_output_tokens": 4096}
                for stage in ("pr_summary", "aggregate", "verify")
            },
        }
    )
