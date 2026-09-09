"""Execute a summary tree using exact input versions and on-request caching."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from altiscope.aggregate.generate import GeneratedAggregate, generate_aggregate
from altiscope.aggregate.inputs import ReportInput, render_inputs, underlying_pr_urls
from altiscope.aggregate.planner import (
    PlanItem,
    PlanNode,
    estimate_aggregate_request_tokens,
    plan_reduction,
)
from altiscope.llm.provider import Provider
from altiscope.llm.providers import ProviderPool
from altiscope.llm.registry import Registry
from altiscope.llm.router import RoutingDecision, RoutingError, route
from altiscope.llm.tokens import estimate_tokens
from altiscope.prompts import Prompt
from altiscope.schemas.aggregate import AGGREGATE_SCHEMA_VERSION, AggregateOutput, Altitude


class AggregateQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    repository: str
    since: datetime
    until: datetime
    altitude: Altitude

    @field_validator("repository")
    @classmethod
    def repository_name(cls, value: str) -> str:
        parts = value.split("/")
        if len(parts) != 2 or any(
            not part or not all(c.isalnum() or c in "._-" for c in part) for part in parts
        ):
            raise ValueError("Expected repository as owner/name")
        return value

    @field_validator("since", "until")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered_window(self) -> AggregateQuery:
        if self.until < self.since:
            raise ValueError("until must be greater than or equal to since")
        return self

    def instruction(self) -> str:
        return (
            f"Repository: {self.repository}\nMerged from {self.since.isoformat()} "
            f"through {self.until.isoformat()} (inclusive).\nReader altitude: {self.altitude.value}"
        )


class SavedAggregate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    query: AggregateQuery
    input_hash: str
    inputs: tuple[ReportInput, ...]
    output: AggregateOutput | None
    errors: tuple[str, ...]
    created_at: datetime
    model_id: str
    provider: str
    prompt_version: str
    prompt_hash: str
    prompt_source: str
    settings: dict[str, Any]

    @property
    def pr_urls(self) -> tuple[str, ...]:
        return underlying_pr_urls(self.inputs)

    def as_input(self) -> ReportInput:
        if self.output is None:
            raise ValueError("A failed report cannot be summarized")
        return ReportInput(
            "aggregate", self.id, self.output.model_dump_json(), self.pr_urls, self.input_hash
        )


class AggregateStore(Protocol):
    def find(self, input_hash: str) -> SavedAggregate | None: ...
    def get(self, report_id: str) -> SavedAggregate: ...
    def save(
        self,
        report: SavedAggregate,
        generated: GeneratedAggregate,
        *,
        prompt: Prompt,
        decision: RoutingDecision,
        registry: Registry,
        retention: str,
    ) -> None: ...


class MemoryAggregateStore:
    """Credential-free demo storage using the same engine as Postgres."""

    def __init__(self) -> None:
        self.reports: dict[str, SavedAggregate] = {}
        self.generations: dict[str, GeneratedAggregate] = {}

    def find(self, input_hash: str) -> SavedAggregate | None:
        return next(
            (
                r
                for r in reversed(list(self.reports.values()))
                if r.input_hash == input_hash and r.output is not None
            ),
            None,
        )

    def get(self, report_id: str) -> SavedAggregate:
        try:
            return self.reports[report_id]
        except KeyError:
            raise ValueError("Aggregate report not found") from None

    def save(
        self,
        report: SavedAggregate,
        generated: GeneratedAggregate,
        *,
        prompt: Prompt,
        decision: RoutingDecision,
        registry: Registry,
        retention: str,
    ) -> None:
        self.reports[report.id] = report
        self.generations[report.id] = generated


class AggregateError(RuntimeError):
    pass


@dataclass(frozen=True)
class AggregateResult:
    report: SavedAggregate | None
    calls: int
    cache_hits: int


def generation_settings(registry: Registry, decision: RoutingDecision) -> dict[str, Any]:
    model = registry.models[decision.model_id].model_dump(mode="json")
    model["capabilities"] = sorted(registry.models[decision.model_id].capabilities)
    return {
        "model": model,
        "provider": registry.provider_for(decision.model_id).model_dump(mode="json"),
        "stage": registry.stages["aggregate"].model_dump(mode="json"),
        "input_budget_fraction": registry.input_budget_fraction,
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "renderer_version": 1,
    }


def cache_key(
    query: AggregateQuery, inputs: tuple[ReportInput, ...], prompt: Prompt, settings: dict[str, Any]
) -> str:
    payload = dict(
        query=query.model_dump(mode="json"),
        inputs=[asdict(i) for i in inputs],
        prompt_hash=prompt.content_hash,
        settings=settings,
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def aggregate_reports(
    inputs: tuple[ReportInput, ...],
    *,
    query: AggregateQuery,
    store: AggregateStore,
    registry: Registry,
    prompt: Prompt,
    retention: str = "full",
    force: bool = False,
    provider: Provider | None = None,
) -> AggregateResult:
    if prompt.stage != "aggregate" or prompt.schema_version != AGGREGATE_SCHEMA_VERSION:
        raise ValueError("Aggregate generation requires the current aggregate prompt schema")
    if retention not in ("full", "hashes_only"):
        raise ValueError("Unknown payload retention policy")
    if not inputs:
        return AggregateResult(None, 0, 0)
    instruction = query.instruction()
    complete = estimate_aggregate_request_tokens(prompt.body, render_inputs(instruction, inputs))
    try:
        route(registry, "aggregate", complete)
        plan = PlanNode(items=[PlanItem((str(i),), str(i), 0) for i in range(len(inputs))])
    except RoutingError:
        # Plan against the largest eligible capacity; route each actual request separately.
        largest = max(
            registry.input_budget(m, "aggregate") for m in registry.stages["aggregate"].candidates
        )
        overhead = estimate_aggregate_request_tokens(
            prompt.body, instruction + "\n\nInput reports (data):\n[]"
        )
        items = [
            PlanItem(
                (f"{i:012}",),
                str(i),
                estimate_tokens(
                    json.dumps({"report": i + 1, "text": item.text}, ensure_ascii=False)
                ),
            )
            for i, item in enumerate(inputs)
        ]
        plan = plan_reduction(
            items,
            budget_tokens=largest - overhead,
            per_item_overhead=8,
            child_output_tokens=registry.stages["aggregate"].reserved_output_tokens,
        )
    pool = ProviderPool(registry)
    calls = 0
    hits = 0

    def execute(node: PlanNode) -> SavedAggregate:
        nonlocal calls, hits
        supplied = (
            tuple(inputs[int(i.id)] for i in node.items)
            if node.is_leaf
            else tuple(execute(c).as_input() for c in node.children)
        )
        estimated = estimate_aggregate_request_tokens(
            prompt.body, render_inputs(instruction, supplied)
        )
        decision = route(registry, "aggregate", estimated)
        settings = generation_settings(registry, decision)
        key = cache_key(query, supplied, prompt, settings)
        if not force:
            cached = store.find(key)
            if cached is not None:
                hits += 1
                return cached
        generated = generate_aggregate(
            provider or pool.for_model(decision.model_id),
            registry.models[decision.model_id],
            system=prompt.body,
            user=instruction,
            inputs=supplied,
            max_tokens=registry.stages["aggregate"].reserved_output_tokens,
            effort=decision.effort,
            input_budget=registry.input_budget(decision.model_id, "aggregate"),
        )
        calls += len(generated.attempts)
        report = SavedAggregate(
            id=str(uuid4()),
            query=query,
            input_hash=key,
            inputs=supplied,
            output=generated.output,
            errors=generated.errors,
            created_at=datetime.now(UTC),
            model_id=decision.model_id,
            provider=decision.provider,
            prompt_version=prompt.version,
            prompt_hash=prompt.content_hash,
            prompt_source=prompt.source_text,
            settings=settings,
        )
        store.save(
            report,
            generated,
            prompt=prompt,
            decision=decision,
            registry=registry,
            retention=retention,
        )
        if report.output is None:
            raise AggregateError(
                f"Aggregate attempt {report.id} failed: {'; '.join(report.errors)}"
            )
        return report

    return AggregateResult(execute(plan), calls, hits)
