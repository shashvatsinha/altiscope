"""Plan model calls that combine inputs in groups within an estimated token budget.

Sort PlanItems by their supplied order keys, IDs, and token counts. The same inputs and
budget settings produce the same tree. The aggregate service executes the tree and
reuses cached reports under the input and version rules in ADR-0011.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from altiscope.llm.tokens import estimate_tokens
from altiscope.schemas.aggregate import AggregateOutput


class PlanningError(Exception):
    pass


@dataclass(frozen=True, order=True)
class PlanItem:
    """One input to aggregation: a pr_summary (leaf level) or a child aggregate."""

    order_key: tuple[str, ...]
    id: str
    tokens: int


@dataclass
class PlanNode:
    """A leaf holds items that fit in one call. An internal node holds child nodes whose
    outputs are the items of one call."""

    items: list[PlanItem] = field(default_factory=list)
    children: list[PlanNode] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def depth(self) -> int:
        return 1 if self.is_leaf else 1 + max(c.depth for c in self.children)

    @property
    def leaf_count(self) -> int:
        return 1 if self.is_leaf else sum(c.leaf_count for c in self.children)

    @property
    def call_count(self) -> int:
        return 1 + sum(c.call_count for c in self.children)


def _chunk(items: list[PlanItem], budget: int, per_item_overhead: int) -> list[list[PlanItem]]:
    groups: list[list[PlanItem]] = []
    current: list[PlanItem] = []
    used = 0
    for item in items:
        cost = item.tokens + per_item_overhead
        if cost > budget:
            msg = f"item {item.id} needs {cost:,} tokens; budget is {budget:,}"
            raise PlanningError(msg)
        if used + cost > budget and current:
            groups.append(current)
            current, used = [], 0
        current.append(item)
        used += cost
    if current:
        groups.append(current)
    return groups


def _first_key(node: PlanNode) -> tuple[str, ...]:
    if node.items:
        return node.items[0].order_key
    return _first_key(node.children[0])


def plan_reduction(
    items: list[PlanItem],
    *,
    budget_tokens: int,
    per_item_overhead: int = 50,
    child_output_tokens: int = 4_000,
) -> PlanNode:
    """Build the tree. `budget_tokens` is the routed model's input budget for the
    aggregate stage. `child_output_tokens` is the planning estimate for how large a
    child aggregate is when it becomes an input to its parent."""
    if per_item_overhead < 0 or child_output_tokens <= 0 or any(i.tokens < 0 for i in items):
        raise PlanningError("Token sizes must be nonnegative and child output must be positive")
    if not items:
        msg = "nothing to aggregate"
        raise PlanningError(msg)
    if budget_tokens <= 0:
        msg = "budget must be positive"
        raise PlanningError(msg)
    ordered = sorted(items)
    groups = _chunk(ordered, budget_tokens, per_item_overhead)
    if len(groups) == 1:
        return PlanNode(items=groups[0])

    children = [PlanNode(items=g) for g in groups]
    while len(children) > 1:
        # Each child becomes an item for the next level, keyed by its first item so the
        # ordering stays deterministic.
        as_items = [
            PlanItem(order_key=_first_key(c), id=f"node:{i}", tokens=child_output_tokens)
            for i, c in enumerate(children)
        ]
        next_groups = _chunk(as_items, budget_tokens, per_item_overhead)
        if len(next_groups) == 1:
            return PlanNode(children=children)
        if max(len(g) for g in next_groups) < 2:
            msg = (
                f"budget {budget_tokens:,} fits fewer than two child summaries of "
                f"{child_output_tokens:,} tokens; the tree cannot reduce"
            )
            raise PlanningError(msg)
        next_children: list[PlanNode] = []
        cursor = 0
        for g in next_groups:
            next_children.append(PlanNode(children=children[cursor : cursor + len(g)]))
            cursor += len(g)
        children = next_children
    return children[0]


def calculate_aggregate_input_budget(
    model_context_window: int,
    *,
    budget_fraction: float = 0.75,
    reserved_output_tokens: int = 16_000,
    system_prompt_tokens: int = 1_000,
    overhead_tokens: int = 256,
    schema_tokens: int | None = None,
) -> int:
    """Remaining item budget after system, schema, envelope and output reservation.

    Callers must supply actual system and user-envelope costs. Execution must also
    estimate each fully rendered request, including repair instructions.
    """
    if schema_tokens is None:
        schema_tokens = estimate_tokens(
            json.dumps(AggregateOutput.model_json_schema(), sort_keys=True)
        )
    if model_context_window <= 0 or not 0 < budget_fraction <= 1:
        raise PlanningError("Invalid model context window or budget fraction")
    if min(reserved_output_tokens, system_prompt_tokens, overhead_tokens, schema_tokens) < 0:
        raise PlanningError("Token reservations must be nonnegative")
    usable = int(model_context_window * budget_fraction) - reserved_output_tokens
    budget = usable - system_prompt_tokens - overhead_tokens - schema_tokens
    if budget <= 0:
        raise PlanningError("No input budget remains after request and output reservations")
    return budget


def estimate_aggregate_request_tokens(system: str, user: str) -> int:
    schema = json.dumps(AggregateOutput.model_json_schema(), sort_keys=True)
    return estimate_tokens(system) + estimate_tokens(user) + estimate_tokens(schema) + 256
