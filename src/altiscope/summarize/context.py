"""Prepare deterministic code-first model input for one pull request."""

from __future__ import annotations

from dataclasses import dataclass

from altiscope.ingest.diff_policy import InputManifest
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.summarize.facts import PrFacts


@dataclass
class PrContext:
    snapshot: PullRequestSnapshot
    facts: PrFacts
    manifest: InputManifest

    def patch_for(self, path: str) -> str | None:
        for f in self.snapshot.files:
            if f.path == path:
                return f.patch
        return None


def render_user_prompt(ctx: PrContext) -> str:
    """Deterministic text the model reads. Code changes precede PR prose."""
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

    parts.append("\n\n# 3. Code changes (primary evidence)\n")
    parts.append(
        "Use the included patches below as the primary evidence for what changed. "
        "A PR description or comment can explain intent, but cannot establish that code changed."
    )

    parts.append("\n\n# 4. Patches of included files (primary source)\n")
    for path in ctx.manifest.included_paths:
        patch = ctx.patch_for(path)
        parts.append(f"<file path={path!r}>")
        parts.append(patch or "")
        parts.append("</file>")

    parts.append("\n\n# 5. Pull request context\n")
    parts.append(f"Repository: {s.repository}  Number: #{s.number}  Base: {s.base_ref}")
    parts.append(f"Title: {s.title}")
    parts.append("Description (verbatim; context, not proof of code change):")
    parts.append("<description>")
    parts.append(s.body if s.body.strip() else "(empty)")
    parts.append("</description>")

    parts.append("\n\n# 6. Commits, reviews and comments\n")
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
    parts.append("\nComments:")
    if s.comments:
        for c in sorted(s.comments, key=lambda c: (c.created_at, c.kind, c.github_id)):
            where = f" on {c.path}:{c.line}" if c.path else ""
            parts.append(f"<comment kind={c.kind.value} author={c.author_login}{where}>")
            parts.append(c.body)
            parts.append("</comment>")
    else:
        parts.append("- (none)")

    return "\n".join(parts)
