"""Enforce provenance on an aggregate output before storage.

Every aggregate claim must cite only source tokens that were in the material. Claims
that cite nothing valid are dropped and the drop is recorded; it counts against the
aggregate in the same way uncited inputs do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from altiscope.schemas.aggregate import AggregateClaim, AggregateOutput


@dataclass
class DroppedClaim:
    text: str
    unknown_sources: list[str]


@dataclass
class AggregateValidation:
    output: AggregateOutput
    dropped: list[DroppedClaim] = field(default_factory=list)
    trimmed_sources: int = 0  # unknown tokens removed from claims that survived

    @property
    def ok(self) -> bool:
        return not self.dropped and self.trimmed_sources == 0


def validate_aggregate(output: AggregateOutput, allowed_sources: set[str]) -> AggregateValidation:
    kept: list[AggregateClaim] = []
    dropped: list[DroppedClaim] = []
    trimmed = 0
    for claim in output.claims:
        valid = [s for s in claim.sources if s in allowed_sources]
        unknown = [s for s in claim.sources if s not in allowed_sources]
        if not valid:
            dropped.append(DroppedClaim(text=claim.text, unknown_sources=unknown))
            continue
        trimmed += len(unknown)
        # Deduplicate while preserving order.
        seen: set[str] = set()
        deduped = [s for s in valid if not (s in seen or seen.add(s))]
        kept.append(claim.model_copy(update={"sources": deduped}))
    if not kept:
        msg = "every aggregate claim cited unknown sources"
        raise ValueError(msg)
    cleaned = output.model_copy(update={"claims": kept})
    return AggregateValidation(output=cleaned, dropped=dropped, trimmed_sources=trimmed)
