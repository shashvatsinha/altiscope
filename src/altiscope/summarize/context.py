"""Prepare model input for one pull request and maps for checking comment references.

Comments use per-call tokens (c1, c2, ...) mapped to (kind, GitHub ID). The validator rejects
unknown tokens. Files use paths and commits use SHA prefixes checked against the snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from altiscope.ingest.diff_policy import InputManifest, PolicyOutcome
from altiscope.ingest.snapshot import CommentKind, PullRequestSnapshot
from altiscope.summarize.facts import PrFacts


@dataclass
class PrContext:
    snapshot: PullRequestSnapshot
    facts: PrFacts
    manifest: InputManifest
    outcome: PolicyOutcome
    comment_tokens: dict[str, tuple[CommentKind, int]] = field(default_factory=dict)

    @property
    def included_paths(self) -> set[str]:
        return {d.path for d in self.outcome.included}

    def patch_for(self, path: str) -> str | None:
        for f in self.snapshot.files:
            if f.path == path:
                return f.patch
        return None


def build_context(
    snapshot: PullRequestSnapshot, outcome: PolicyOutcome, facts: PrFacts, manifest: InputManifest
) -> PrContext:
    ordered = sorted(snapshot.comments, key=lambda c: (c.created_at, c.kind, c.github_id))
    tokens = {f"c{i}": (c.kind, c.github_id) for i, c in enumerate(ordered, start=1)}
    return PrContext(
        snapshot=snapshot, facts=facts, manifest=manifest, outcome=outcome, comment_tokens=tokens
    )


def render_user_prompt(ctx: PrContext) -> str:
    """Deterministic text the model reads. Order matches prompts/pr_summary/v1.md."""
    s = ctx.snapshot
    parts: list[str] = []

    parts.append("# 1. Computed facts (authoritative)\n")
    parts.append(ctx.facts.model_dump_json(indent=2))

    parts.append("\n\n# 2. Input manifest\n")
    parts.append(f"Included files ({len(ctx.manifest.included_paths)}):")
    parts.extend(f"- {p}" for p in ctx.manifest.included_paths)
    if ctx.manifest.excluded:
        parts.append(
            f"\nExcluded files ({len(ctx.manifest.excluded)}, "
            f"{ctx.manifest.excluded_lines} lines not shown to you):"
        )
        parts.extend(
            f"- {e.path} [{e.reason.value}] +{e.additions}/-{e.deletions}"
            for e in ctx.manifest.excluded
        )
    else:
        parts.append("\nNo files were excluded.")

    parts.append("\n\n# 3. Pull request\n")
    parts.append(f"Repository: {s.repository}  Number: #{s.number}  Base: {s.base_ref}")
    parts.append(f"Title: {s.title}")
    parts.append("Description (verbatim):")
    parts.append("<description>")
    parts.append(s.body if s.body.strip() else "(empty)")
    parts.append("</description>")

    parts.append("\n\n# 4. Patches of included files\n")
    for path in ctx.manifest.included_paths:
        patch = ctx.patch_for(path)
        parts.append(f"<file path={path!r}>")
        parts.append(patch or "")
        parts.append("</file>")

    parts.append("\n\n# 5. Commits, reviews and comments\n")
    parts.append("Commits:")
    parts.extend(f"- {c.sha}: {c.message.splitlines()[0] if c.message else ''}" for c in s.commits)
    parts.append("\nReviews:")
    if s.reviews:
        parts.extend(
            f"- {r.author_login} {r.state.value}" + (f": {r.body}" if r.body.strip() else "")
            for r in s.reviews
        )
    else:
        parts.append("- (none)")
    parts.append("\nComments (cite by id):")
    by_id = {(c.kind, c.github_id): c for c in s.comments}
    if ctx.comment_tokens:
        for token, identity in ctx.comment_tokens.items():
            c = by_id[identity]
            where = f" on {c.path}:{c.line}" if c.path else ""
            parts.append(f"<comment id={token} kind={c.kind.value} author={c.author_login}{where}>")
            parts.append(c.body)
            parts.append("</comment>")
    else:
        parts.append("- (none)")

    return "\n".join(parts)
