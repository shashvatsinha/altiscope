"""Validate report navigation without trimming prose or assessing individual claims."""

from __future__ import annotations

from altiscope.schemas.aggregate import AggregateOutput


def validate_aggregate(output: AggregateOutput, allowed_sources: set[str]) -> AggregateOutput:
    """Reject unknown report tokens; the caller may request one replacement output.

    At a parent node, allowed_sources is the union of original PR tokens cited by
    its children, not every PR that was supplied to those children. This prevents
    a parent from restoring references omitted at an earlier reduction level.
    Empty references are usable output with zero citation coverage.
    """
    unknown = set(output.sources) - allowed_sources
    if unknown:
        raise ValueError("Unknown report source tokens: " + ", ".join(sorted(unknown)))
    return output
