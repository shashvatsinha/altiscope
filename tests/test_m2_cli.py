from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from altiscope.cli.main import app
from tests.conftest import REPO_ROOT


@pytest.mark.parametrize("altitude", ["ic", "manager", "exec"])
def test_demo_samples(altitude: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(REPO_ROOT)
    result = CliRunner().invoke(app, ["demo", "--stage", "aggregate", "--altitude", altitude])
    assert result.exit_code == 0, result.exception
    assert result.output == (REPO_ROOT / f"examples/m2/sample-{altitude}.txt").read_text()
    assert "coverage" not in result.output.lower()


def test_multilevel_demo_and_cli_validation(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(REPO_ROOT)
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--stage", "aggregate", "--multi-level"])
    assert result.exit_code == 0, result.exception
    assert result.output == (REPO_ROOT / "examples/m2/sample-multilevel.txt").read_text()
    for args in (
        ["--since", "2026-06-30", "--until", "2026-06-01"],
        ["--since", "bad", "--until", "2026-06-01"],
        ["--since", "2026-06-01", "--until", "2026-06-30", "--altitude", "unknown"],
    ):
        invalid = runner.invoke(app, ["aggregate", "o/r", *args])
        assert invalid.exit_code == 1
        assert "Could not aggregate" in invalid.output


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres")
def test_persisted_tree_drilldown_and_empty_cli(database: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(REPO_ROOT)
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--stage", "aggregate", "--persist", "--multi-level"])
    assert result.exit_code == 0, result.exception
    root = re.search(r"Inspect: altiscope show-aggregate ([a-f0-9-]+)", result.output)
    assert root
    shown = runner.invoke(app, ["show-aggregate", root[1], "--verbose"])
    assert shown.exit_code == 0, shown.exception
    assert "Exact prompt file:" in shown.output and "Model-call attempts:" in shown.output
    assert "Provider: fixture" in shown.output
    children = re.findall(r"altiscope show-aggregate ([a-f0-9-]+)", shown.output)
    assert len(children) == 2
    pr_ids = []
    for child in children:
        child_report = runner.invoke(app, ["show-aggregate", child])
        assert child_report.exit_code == 0, child_report.exception
        pr_ids.extend(re.findall(r"altiscope show-report (\d+)", child_report.output))
    assert len(pr_ids) == 4
    pr = runner.invoke(app, ["show-report", pr_ids[0], "--verbose"])
    assert pr.exit_code == 0 and "Exact prompt file:" in pr.output and "billing/pull/1" in pr.output
    empty = runner.invoke(
        app,
        [
            "aggregate",
            "altiscope-demo/billing",
            "--since",
            "1900-01-01",
            "--until",
            "1900-01-01",
            "--local-only",
        ],
    )
    assert empty.exit_code == 0, empty.exception
    assert "0 PRs merged" in empty.output


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres")
def test_aggregate_cli_generates_then_caches(
    database: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    import yaml

    from altiscope.aggregate.demo import run_demo
    from altiscope.llm.providers import ProviderPool
    from altiscope.summarize.fixture import FixtureProvider, fixture_registry
    from tests.test_aggregate_generation import good_output

    monkeypatch.chdir(REPO_ROOT)
    run_demo("manager", persist=True)
    config: Path = tmp_path / "models.yaml"
    config.write_text(yaml.safe_dump(fixture_registry().model_dump(mode="json")))
    monkeypatch.setenv("ALTISCOPE_MODELS_CONFIG", str(config))
    provider = FixtureProvider([good_output().model_dump_json()])

    def provide(self: ProviderPool, model_id: str) -> FixtureProvider:
        return provider

    monkeypatch.setattr(ProviderPool, "for_model", provide)
    args = [
        "aggregate",
        "altiscope-demo/billing",
        "--since",
        "2026-06-01",
        "--until",
        "2026-06-30",
        "--altitude",
        "manager",
        "--local-only",
    ]
    first = CliRunner().invoke(app, [*args, "--regenerate"])
    assert first.exit_code == 0, first.exception
    assert "aggregate model calls: 1" in first.output
    second = CliRunner().invoke(app, args)
    assert second.exit_code == 0, second.exception
    assert "aggregate model calls: 0" in second.output
    assert provider.calls == 1
