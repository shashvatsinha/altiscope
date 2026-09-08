"""Render a usable review with application-owned PR provenance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from altiscope.schemas.pr_summary import PrReviewOutput
from altiscope.summarize.context import PrContext


class PublicationState(StrEnum):
    published = "published"
    needs_review = "needs_review"


@dataclass(frozen=True)
class Publication:
    state: PublicationState
    output: PrReviewOutput | None
    errors: tuple[str, ...]
    semantic_status: str = "unverified"


def assess(output: PrReviewOutput | None) -> Publication:
    if output is None or not output.review.strip():
        return Publication(PublicationState.needs_review, None, ("No usable model review",))
    return Publication(PublicationState.published, output, ())


def render_account(publication: Publication, ctx: PrContext, *, verbose: bool = False) -> str:
    checked = assess(publication.output)
    lines = [f"PR {ctx.snapshot.repository}#{ctx.snapshot.number}", ctx.snapshot.html_url]
    lines.append(f"Status: {checked.state.value}; interpretation unverified")
    if checked.output is not None and publication.state == PublicationState.published:
        lines.extend(["", checked.output.review])
    else:
        lines.append("Generated review unavailable.")
        errors = publication.errors or checked.errors
        lines.extend(f"Reason: {error}" for error in errors)
    if ctx.manifest.excluded:
        lines.append(
            f"Input omissions: {len(ctx.manifest.excluded)} files excluded from model input."
        )
    if verbose:
        lines.extend(["\nComputed facts:", ctx.facts.model_dump_json(indent=2)])
        lines.extend(["\nInput omissions:", ctx.manifest.model_dump_json(indent=2)])
    return "\n".join(lines) + "\n"
