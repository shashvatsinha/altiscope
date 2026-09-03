"""The model registry: which models exist and how each stage chooses among them.

Loaded from config/models.yaml. See docs/adr/0005-model-registry-routing.md.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from altiscope.llm.types import STAGES, Effort, Stage


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider: str
    display_name: str
    context_window: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    input_usd_per_mtok: float = Field(ge=0)
    output_usd_per_mtok: float = Field(ge=0)


class StageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[str] = Field(min_length=1, description="Preference order.")
    effort: Effort = "high"
    reserved_output_tokens: int = Field(gt=0)
    must_differ_from_producer: bool = False


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: dict[str, ModelSpec]
    input_budget_fraction: float = Field(gt=0, le=1, default=0.75)
    stages: dict[Stage, StageConfig]

    @model_validator(mode="before")
    @classmethod
    def _inject_ids(cls, data: Any) -> Any:
        # Allow `models: {id: {...}}` without repeating the id inside each entry.
        if isinstance(data, dict):
            raw_models = data.get("models")  # type: ignore[union-attr]
            if isinstance(raw_models, dict):
                for model_id, spec in raw_models.items():  # type: ignore[union-attr]
                    if isinstance(spec, dict) and "id" not in spec:
                        spec["id"] = model_id  # type: ignore[index]
        return data

    @model_validator(mode="after")
    def _check_references(self) -> Registry:
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

    def input_budget(self, model_id: str, stage: Stage) -> int:
        """Largest input (in tokens) the router will send to `model_id` for `stage`."""
        spec = self.models[model_id]
        usable = math.floor(spec.context_window * self.input_budget_fraction)
        return max(0, usable - self.stages[stage].reserved_output_tokens)
