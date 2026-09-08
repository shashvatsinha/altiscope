"""Publication boundary: fail closed and render only checked model claims."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from altiscope.schemas.pr_summary import PrAccountOutput
from altiscope.summarize.context import PrContext
from altiscope.summarize.validate import validate_summary


class PublicationState(StrEnum):
    citation_valid = "citation_valid"
    needs_review = "needs_review"


@dataclass(frozen=True)
class Publication:
    state: PublicationState
    output: PrAccountOutput | None
    errors: tuple[str, ...]
    semantic_status: str = "unverified"


def assess(output: PrAccountOutput | None, ctx: PrContext) -> Publication:
    if output is None:
        return Publication(PublicationState.needs_review, None, ("No valid model output",))
    result = validate_summary(output, ctx)
    errors = tuple(result.errors + result.warnings)
    if errors:
        return Publication(PublicationState.needs_review, None, errors)
    return Publication(PublicationState.citation_valid, output, ())


def render_account(publication: Publication, ctx: PrContext, *, verbose: bool = False) -> str:
    # Revalidate at the presentation boundary; callers cannot label arbitrary text valid.
    checked = assess(publication.output, ctx)
    lines = [f"PR {ctx.snapshot.repository}#{ctx.snapshot.number}", ctx.snapshot.html_url]
    lines.append(f"Status: {checked.state.value}; interpretation unverified")
    if checked.output is not None and publication.state == PublicationState.citation_valid:
        for ordinal, claim in enumerate(checked.output.claims, 1):
            lines.append(f"\n{ordinal}. {claim.text}")
            if not verbose:
                continue
            for evidence in claim.evidence:
                lines.append(f"   Evidence: {evidence.model_dump_json(exclude_none=True)}")
                if evidence.path:
                    excerpt = ctx.patch_for(evidence.path) or ""
                elif evidence.comment_id:
                    identity = ctx.comment_tokens[evidence.comment_id]
                    excerpt = next(
                        c.body for c in ctx.snapshot.comments if (c.kind, c.github_id) == identity
                    )
                elif evidence.commit_sha:
                    excerpt = next(
                        c.message
                        for c in ctx.snapshot.commits
                        if c.sha.lower().startswith(evidence.commit_sha.lower())
                    )
                else:
                    excerpt = evidence.quote or ""
                lines.extend(f"   | {line}" for line in excerpt.splitlines())
    else:
        lines.append("Generated account withheld pending review.")
        if verbose and checked.errors:
            lines.append("Validation errors:")
            lines.extend(f"- {error}" for error in checked.errors)
    if verbose:
        lines.extend(["\nComputed facts:", ctx.facts.model_dump_json(indent=2)])
        lines.extend(["\nInput omissions:", ctx.manifest.model_dump_json(indent=2)])
        lines.append("Citation checks establish source membership, not semantic support.")
    return "\n".join(lines) + "\n"
