from __future__ import annotations

from altiscope.prompts import latest_prompt, list_prompts
from tests.conftest import REPO_ROOT


def test_shipped_prompts_parse_and_hash():
    prompts = list_prompts(REPO_ROOT / "prompts")
    stages = {p.stage for p in prompts}
    assert stages == {"pr_summary", "aggregate", "verify"}
    for p in prompts:
        assert p.schema_version == int(p.version[1:])
        assert len(p.content_hash) == 64
        assert p.body.strip()
    by_stage = {p.stage: p.body for p in prompts}
    assert "never evaluate people" in by_stage["pr_summary"]
    assert "never people" in by_stage["aggregate"]
    assert "cannot_determine" in by_stage["verify"]


def test_latest_prompt_per_stage():
    p = latest_prompt(REPO_ROOT / "prompts", "pr_summary")
    assert p.version == "v2"
    assert "There is no separate headline or narrative" in p.body
