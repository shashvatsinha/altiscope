"""Which inputs an aggregate cited, and which it left out.

The defence against selective emphasis (ADR-0007). Computed for every aggregate at every
level of the reduction tree and stored in aggregate_summaries.coverage.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from altiscope.schemas.aggregate import AggregateClaim

DEFAULT_LOW_COVERAGE_THRESHOLD = 0.6


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_count: int
    cited_count: int
    cited: list[str] = Field(description="input ids cited by at least one claim, sorted")
    uncited: list[str] = Field(description="input ids no claim cites, sorted")
    ratio: float

    def is_low(self, threshold: float = DEFAULT_LOW_COVERAGE_THRESHOLD) -> bool:
        return self.ratio < threshold


def compute_coverage(
    input_ids: set[str],
    claims: list[AggregateClaim],
    source_to_input: Mapping[str, str],
) -> Coverage:
    """`source_to_input` maps each source token the model could cite (a claim token) to
    the input it belongs to (a pr_summary id or child aggregate id)."""
    cited: set[str] = set()
    for claim in claims:
        for token in claim.sources:
            owner = source_to_input.get(token)
            if owner is not None and owner in input_ids:
                cited.add(owner)
    uncited = input_ids - cited
    ratio = (len(cited) / len(input_ids)) if input_ids else 1.0
    return Coverage(
        input_count=len(input_ids),
        cited_count=len(cited),
        cited=sorted(cited),
        uncited=sorted(uncited),
        ratio=round(ratio, 4),
    )
