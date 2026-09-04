"""The provider protocol every model backend implements.

Deliberately two methods. Everything else (routing, prompt assembly, validation,
storage) is provider-independent and lives elsewhere. Adapters differ only in how they
obtain schema-shaped JSON from the model; the pipeline's own validation against the PR
snapshot is the correctness guarantee, not the provider's schema enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from altiscope.llm.registry import ModelSpec, StructuredOutputMode
from altiscope.llm.types import Effort

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class GenerationResult(Generic[T]):
    parsed: T | None
    raw_text: str
    model_id: str
    stop_reason: str  # end_turn | max_tokens | refusal | invalid_output | unknown
    usage: Usage
    latency_ms: int
    output_mode: StructuredOutputMode
    provider_request_id: str | None = None
    refusal_category: str | None = None
    validation_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.parsed is not None and self.stop_reason == "end_turn"


class Provider(Protocol):
    name: str

    def generate_structured(
        self,
        *,
        model: ModelSpec,
        system: str,
        user: str,
        output_type: type[T],
        max_tokens: int,
        effort: Effort,
    ) -> GenerationResult[T]: ...

    def count_tokens(self, *, model: ModelSpec, system: str, user: str) -> int:
        """Exact when the model advertises `token_counting`; an overestimate otherwise."""
        ...
