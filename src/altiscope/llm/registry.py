"""The model registry: which providers and models exist, and how each stage chooses.

Loaded from config/models.yaml. See docs/adr/0005-model-registry-routing.md.

Two ideas keep this provider-neutral:

* A *provider* is a configured endpoint, not a vendor. One `openai_compatible` adapter
  serves OpenAI, Azure OpenAI, Ollama, vLLM, LM Studio, llama.cpp, Groq, Together,
  OpenRouter and any other server that speaks the chat-completions protocol. The same
  kind can be declared several times with different base URLs.
* A *model* declares capabilities. The adapter uses the best structured-output mode the
  model supports and the pipeline validates the output the same way regardless, so a
  model without native JSON-schema support is slower to converge, not unsafe.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from altiscope.llm.types import STAGES, Effort, Stage

ProviderKind = Literal["anthropic", "openai_compatible"]

Capability = Literal[
    "json_schema",  # server-enforced JSON schema output (structured outputs / guided decoding)
    "json_mode",  # server guarantees syntactically valid JSON, schema is prompted
    "reasoning_effort",  # accepts an effort / reasoning level parameter
    "token_counting",  # has a token-count endpoint for this model
]

StructuredOutputMode = Literal["native", "json_mode", "prompt"]

ProducerIndependence = Literal["none", "model", "provider"]


class ProviderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ProviderKind
    base_url: str | None = Field(default=None, description="Endpoint; None uses the SDK default.")
    api_key_env: str | None = Field(
        default=None, description="Environment variable holding the key; None for unauthenticated."
    )
    timeout_seconds: float = Field(default=600, gt=0)


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Registry id, used in routing and recorded on llm_calls.")
    provider: str
    model_name: str | None = Field(
        default=None, description="Name sent to the provider when it differs from id."
    )
    display_name: str
    context_window: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    input_usd_per_mtok: float = Field(default=0, ge=0)
    output_usd_per_mtok: float = Field(default=0, ge=0)
    capabilities: set[Capability] = Field(default_factory=set)

    @property
    def wire_name(self) -> str:
        return self.model_name or self.id

    @property
    def structured_output_mode(self) -> StructuredOutputMode:
        if "json_schema" in self.capabilities:
            return "native"
        if "json_mode" in self.capabilities:
            return "json_mode"
        return "prompt"


class StageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[str] = Field(min_length=1, description="Preference order.")
    effort: Effort = "high"
    reserved_output_tokens: int = Field(gt=0)
    producer_independence: ProducerIndependence = Field(
        default="none",
        description=(
            "For verification: 'model' skips the model that produced the artifact; "
            "'provider' skips every model from the producer's provider."
        ),
    )


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: dict[str, ProviderSpec]
    models: dict[str, ModelSpec]
    input_budget_fraction: float = Field(gt=0, le=1, default=0.75)
    stages: dict[Stage, StageConfig]

    @model_validator(mode="before")
    @classmethod
    def _inject_keys(cls, data: Any) -> Any:
        # Allow `models: {id: {...}}` and `providers: {name: {...}}` without repeating
        # the key inside each entry.
        if isinstance(data, dict):
            for section, key in (("models", "id"), ("providers", "name")):
                raw = data.get(section)  # type: ignore[union-attr]
                if isinstance(raw, dict):
                    for entry_key, spec in raw.items():  # type: ignore[union-attr]
                        if isinstance(spec, dict) and key not in spec:
                            spec[key] = entry_key  # type: ignore[index]
        return data

    @model_validator(mode="after")
    def _check_references(self) -> Registry:
        for model in self.models.values():
            if model.provider not in self.providers:
                msg = f"model '{model.id}' names unknown provider '{model.provider}'"
                raise ValueError(msg)
        for stage in STAGES:
            if stage not in self.stages:
                msg = f"registry is missing stage '{stage}'"
                raise ValueError(msg)
        for stage, cfg in self.stages.items():
            for candidate in cfg.candidates:
                if candidate not in self.models:
                    msg = f"stage '{stage}' names unknown model '{candidate}'"
                    raise ValueError(msg)
                if cfg.reserved_output_tokens > self.models[candidate].max_output_tokens:
                    msg = (
                        f"stage '{stage}' reserves {cfg.reserved_output_tokens} output tokens "
                        f"but '{candidate}' allows at most "
                        f"{self.models[candidate].max_output_tokens}"
                    )
                    raise ValueError(msg)
        return self

    @classmethod
    def load(cls, path: Path | str) -> Registry:
        with Path(path).open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls.model_validate(data)

    def provider_for(self, model_id: str) -> ProviderSpec:
        return self.providers[self.models[model_id].provider]

    def input_budget(self, model_id: str, stage: Stage) -> int:
        """Largest input (in tokens) the router will send to `model_id` for `stage`."""
        spec = self.models[model_id]
        usable = math.floor(spec.context_window * self.input_budget_fraction)
        return max(0, usable - self.stages[stage].reserved_output_tokens)
