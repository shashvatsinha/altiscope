"""Check summary references against the supplied PR context and report language warnings.

Returns errors and warnings for the generation and publication services.
These checks establish that references match the material, not that claims are supported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from altiscope.schemas.pr_summary import Evidence, EvidenceType, PrAccountOutput, PrSummaryOutput
from altiscope.summarize.context import PrContext

_WS_RE = re.compile(r"\s+")

# Flag these phrases as warnings for review; context may make a use legitimate.
_EVALUATIVE_WORDS: tuple[str, ...] = (
    "impressive",
    "sloppy",
    "lazy",
    "brilliant",
    "careless",
    "diligent",
    "hardworking",
    "productive",
    "unproductive",
    "struggled",
    "excellent work",
    "poor work",
    "great job",
)
_EVALUATIVE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _EVALUATIVE_WORDS) + r")\b", re.IGNORECASE
)


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def lint_language(text: str) -> list[str]:
    return [f"evaluative language: {m.group(1)!r}" for m in _EVALUATIVE_RE.finditer(text)]


def _check_evidence(ev: Evidence, ctx: PrContext, where: str) -> str | None:
    s = ctx.snapshot
    if ev.type in (EvidenceType.file, EvidenceType.hunk):
        assert ev.path is not None
        if ev.path not in ctx.included_paths:
            shown = "excluded from" if any(f.path == ev.path for f in s.files) else "not in"
            return f"{where}: cites file {ev.path!r} which is {shown} the material"
        if ev.type is EvidenceType.hunk:
            assert ev.hunk_header is not None
            patch = ctx.patch_for(ev.path) or ""
            if (
                not re.fullmatch(
                    r"@@ -[0-9]+(?:,[0-9]+)? \+[0-9]+(?:,[0-9]+)? @@[^\n]*", ev.hunk_header
                )
                or ev.hunk_header not in patch.splitlines()
            ):
                return f"{where}: hunk {ev.hunk_header!r} not found in {ev.path!r}"
        return None
    if ev.type is EvidenceType.description:
        assert ev.quote is not None
        if not _norm(ev.quote) or _norm(ev.quote) not in _norm(s.body):
            return f"{where}: quote not found in description: {ev.quote!r}"
        return None
    if ev.type is EvidenceType.pr_title:
        assert ev.quote is not None
        if not _norm(ev.quote) or _norm(ev.quote) not in _norm(s.title):
            return f"{where}: quote not found in title: {ev.quote!r}"
        return None
    if ev.type is EvidenceType.review_comment:
        assert ev.comment_id is not None
        if ev.comment_id not in ctx.comment_tokens:
            return f"{where}: unknown comment id {ev.comment_id!r}"
        return None
    if ev.type is EvidenceType.commit:
        assert ev.commit_sha is not None
        if (
            not re.fullmatch(r"[0-9a-fA-F]{7,40}", ev.commit_sha)
            or sum(c.sha.lower().startswith(ev.commit_sha.lower()) for c in s.commits) != 1
        ):
            return f"{where}: unknown commit {ev.commit_sha!r}"
        return None
    return f"{where}: unhandled evidence type {ev.type}"  # pragma: no cover


def validate_summary(output: PrSummaryOutput | PrAccountOutput, ctx: PrContext) -> ValidationResult:
    result = ValidationResult()
    for i, claim in enumerate(output.claims, start=1):
        if not any(ev.type in (EvidenceType.file, EvidenceType.hunk) for ev in claim.evidence):
            result.errors.append(
                f"claim {i}: must cite at least one included file or diff hunk; "
                "PR prose alone cannot establish a code change"
            )
        for j, ev in enumerate(claim.evidence, start=1):
            error = _check_evidence(ev, ctx, where=f"claim {i} evidence {j}")
            if error:
                result.errors.append(error)
        result.warnings.extend(f"claim {i}: {w}" for w in lint_language(claim.text))
    if isinstance(output, PrSummaryOutput):
        result.warnings.extend(f"narrative: {w}" for w in lint_language(output.narrative))
        result.warnings.extend(f"headline: {w}" for w in lint_language(output.headline))
    return result
