"""Select patch text for model input and record why files were excluded.

Rules cover generated files, dependencies, unavailable patches, and size limits.
The input manifest lists exclusions for the model. Displaying them to readers remains
unbuilt. Keep rules conservative: excluded files may contain relevant changes.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from altiscope.ingest.snapshot import PrFile


class ExclusionReason(StrEnum):
    lockfile = "lockfile"
    generated = "generated"
    vendored = "vendored"
    binary = "binary"
    minified = "minified"
    oversize = "oversize"
    no_patch = "no_patch"


_LOCKFILE_NAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "bun.lock",
        "poetry.lock",
        "uv.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "go.sum",
        "composer.lock",
        "Gemfile.lock",
        "packages.lock.json",
        "mix.lock",
        "flake.lock",
        "pubspec.lock",
    }
)

_GENERATED_GLOBS: tuple[str, ...] = (
    "*.pb.go",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.pb.cc",
    "*.pb.h",
    "*.generated.*",
    "*.g.dart",
    "*.freezed.dart",
    "*.snap",
    "*.map",
    "*.d.ts.map",
    "*.svg",  # usually generated or design assets; huge and unreadable as a diff
    "*.ipynb",  # embedded outputs make diffs unreadable; revisit with a notebook-aware reader
)
_GENERATED_DIR_PARTS: frozenset[str] = frozenset({"__snapshots__", "dist", "build", ".generated"})
_VENDORED_DIR_PARTS: frozenset[str] = frozenset(
    {"vendor", "node_modules", "third_party", "thirdparty"}
)
_MINIFIED_SUFFIXES: tuple[str, ...] = (".min.js", ".min.css", ".bundle.js")


@dataclass(frozen=True)
class DiffPolicy:
    """Thresholds. Bytes are of patch text."""

    max_patch_bytes: int = 200_000
    max_total_included_bytes: int = 2_500_000
    # A single line this long is a strong signal of minified or embedded data.
    max_line_length: int = 5_000


class FileDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    included: bool
    reason: ExclusionReason | None = None
    additions: int
    deletions: int
    patch_bytes: int


class ExcludedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    reason: ExclusionReason
    additions: int
    deletions: int


class InputManifest(BaseModel):
    """Stored with every summary and shown to the model and the reader."""

    model_config = ConfigDict(extra="forbid")

    included_paths: list[str]
    excluded: list[ExcludedFile]
    included_patch_bytes: int
    excluded_lines: int = Field(description="additions + deletions in excluded files")
    policy: dict[str, int]


def _path_parts(path: str) -> list[str]:
    return path.split("/")


def classify(pr_file: PrFile, policy: DiffPolicy) -> FileDecision:
    """Decide for one file, independent of the others. Total-size capping is in `apply`."""
    name = _path_parts(pr_file.path)[-1]
    dir_parts = set(_path_parts(pr_file.path)[:-1])
    patch_bytes = len(pr_file.patch.encode("utf-8")) if pr_file.patch else 0

    def excluded(reason: ExclusionReason) -> FileDecision:
        return FileDecision(
            path=pr_file.path,
            included=False,
            reason=reason,
            additions=pr_file.additions,
            deletions=pr_file.deletions,
            patch_bytes=patch_bytes,
        )

    if pr_file.is_binary:
        return excluded(ExclusionReason.binary)
    if pr_file.patch is None:
        return excluded(ExclusionReason.no_patch)
    if name in _LOCKFILE_NAMES:
        return excluded(ExclusionReason.lockfile)
    if dir_parts & _VENDORED_DIR_PARTS:
        return excluded(ExclusionReason.vendored)
    if name.endswith(_MINIFIED_SUFFIXES):
        return excluded(ExclusionReason.minified)
    if dir_parts & _GENERATED_DIR_PARTS or any(
        fnmatch.fnmatch(name, glob) for glob in _GENERATED_GLOBS
    ):
        return excluded(ExclusionReason.generated)
    if any(len(line) > policy.max_line_length for line in pr_file.patch.splitlines()):
        return excluded(ExclusionReason.minified)
    if patch_bytes > policy.max_patch_bytes:
        return excluded(ExclusionReason.oversize)

    return FileDecision(
        path=pr_file.path,
        included=True,
        additions=pr_file.additions,
        deletions=pr_file.deletions,
        patch_bytes=patch_bytes,
    )


@dataclass
class PolicyOutcome:
    decisions: list[FileDecision] = field(default_factory=list)

    @property
    def included(self) -> list[FileDecision]:
        return [d for d in self.decisions if d.included]

    @property
    def excluded(self) -> list[FileDecision]:
        return [d for d in self.decisions if not d.included]


def apply(files: list[PrFile], policy: DiffPolicy | None = None) -> PolicyOutcome:
    """Classify every file, then enforce the total cap by excluding the largest included
    files as `oversize` until the total fits. Order of output matches input order."""
    policy = policy or DiffPolicy()
    decisions = [classify(f, policy) for f in files]

    total = sum(d.patch_bytes for d in decisions if d.included)
    if total > policy.max_total_included_bytes:
        by_size = sorted(
            (i for i, d in enumerate(decisions) if d.included),
            key=lambda i: decisions[i].patch_bytes,
            reverse=True,
        )
        for i in by_size:
            if total <= policy.max_total_included_bytes:
                break
            d = decisions[i]
            decisions[i] = d.model_copy(
                update={"included": False, "reason": ExclusionReason.oversize}
            )
            total -= d.patch_bytes

    return PolicyOutcome(decisions=decisions)


def manifest(outcome: PolicyOutcome, policy: DiffPolicy | None = None) -> InputManifest:
    policy = policy or DiffPolicy()
    excluded = [
        ExcludedFile(path=d.path, reason=d.reason, additions=d.additions, deletions=d.deletions)
        for d in outcome.excluded
        if d.reason is not None
    ]
    return InputManifest(
        included_paths=[d.path for d in outcome.included],
        excluded=excluded,
        included_patch_bytes=sum(d.patch_bytes for d in outcome.included),
        excluded_lines=sum(d.additions + d.deletions for d in outcome.excluded),
        policy={
            "max_patch_bytes": policy.max_patch_bytes,
            "max_total_included_bytes": policy.max_total_included_bytes,
            "max_line_length": policy.max_line_length,
        },
    )
