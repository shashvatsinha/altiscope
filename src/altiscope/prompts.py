"""Versioned prompt files with front matter; the content hash is recorded on every call."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from altiscope.llm.types import STAGES, Stage

_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class Prompt:
    stage: Stage
    version: str
    schema_version: int
    content_hash: str
    body: str
    path: Path


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        msg = "prompt file must start with a --- front matter block"
        raise ValueError(msg)
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, text[match.end() :]


def load_prompt(path: Path) -> Prompt:
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_front_matter(raw)
    stage = meta.get("stage")
    if stage not in STAGES:
        msg = f"{path}: unknown or missing stage {stage!r}"
        raise ValueError(msg)
    if "version" not in meta or "schema_version" not in meta:
        msg = f"{path}: front matter needs version and schema_version"
        raise ValueError(msg)
    # Hash the whole file so a front matter change is a new version too.
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return Prompt(
        stage=stage,  # type: ignore[arg-type]
        version=meta["version"],
        schema_version=int(meta["schema_version"]),
        content_hash=digest,
        body=body.strip() + "\n",
        path=path,
    )


def list_prompts(prompts_dir: Path) -> list[Prompt]:
    return [load_prompt(p) for p in sorted(prompts_dir.glob("*/v*.md"))]


def latest_prompt(prompts_dir: Path, stage: Stage) -> Prompt:
    candidates = [p for p in list_prompts(prompts_dir) if p.stage == stage]
    if not candidates:
        msg = f"no prompt files for stage {stage}"
        raise FileNotFoundError(msg)

    def version_key(p: Prompt) -> int:
        return int(p.version.lstrip("v"))

    return max(candidates, key=version_key)
