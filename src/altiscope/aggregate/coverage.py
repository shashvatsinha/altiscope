"""Compute report reference coverage over original PRs, never intermediate nodes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_LOW_COVERAGE_THRESHOLD = 0.6
COVERAGE_DISCLAIMER = (
    "Input coverage measures which original pull requests are referenced by this report. "
    "Inclusion of an input does not establish semantic completeness or verified accuracy."
)


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_count: int
    cited_count: int
    cited: list[str] = Field(description="original PR tokens referenced by the report, sorted")
    uncited: list[str] = Field(
        description="original PR tokens not referenced by the report, sorted"
    )
    ratio: float
    disclaimer: str = Field(
        default=COVERAGE_DISCLAIMER,
        description="Disclosure that inclusion does not equate to semantic completeness",
    )

    def is_low(self, threshold: float = DEFAULT_LOW_COVERAGE_THRESHOLD) -> bool:
        return self.ratio < threshold


def compute_coverage(input_ids: set[str], cited_sources: list[str]) -> Coverage:
    """Count original PR tokens against the full window, including earlier omissions.

    Intermediate aggregate IDs must never be expanded into all their input PRs.
    Each level carries only the original PR tokens it actually references.
    """
    cited = set(cited_sources)
    if not cited <= input_ids:
        raise ValueError("Coverage contains unknown original PR tokens")
    uncited = input_ids - cited
    return Coverage(
        input_count=len(input_ids),
        cited_count=len(cited),
        cited=sorted(cited),
        uncited=sorted(uncited),
        ratio=round(len(cited) / len(input_ids), 4) if input_ids else 1.0,
    )
