from __future__ import annotations

from altiscope.prompts import latest_prompt, list_prompts, load_prompt
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
    assert p.version == "v3"
    assert p.schema_version == 3
    assert p.path == REPO_ROOT / "prompts" / "pr_summary" / "v3.md"


def test_minimal_baseline_prompts_preserve_current_contracts_and_people_boundary():
    expected = {"pr_summary": 3, "aggregate": 4}
    for stage, schema_version in expected.items():
        prompt = load_prompt(REPO_ROOT / "prompts/baseline" / f"{stage}-v1.md")
        assert prompt.stage == stage
        assert prompt.version == "baseline-v1"
        assert prompt.schema_version == schema_version
        assert "never people" in prompt.body or "never the person" in prompt.body
        assert "confidence" not in prompt.body or "numeric confidence" in prompt.body
