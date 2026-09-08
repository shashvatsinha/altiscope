from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from altiscope.cli.main import app
from tests.conftest import REPO_ROOT


def test_offline_demo_reproduces_reviewed_sample(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(REPO_ROOT)
    result = CliRunner().invoke(app, ["demo"])
    assert result.exit_code == 0, result.output
    assert result.output == (REPO_ROOT / "examples/m1/sample.txt").read_text()


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres")
def test_persisted_demo_and_show(database: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(REPO_ROOT)
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "--persist"])
    assert result.exit_code == 0, result.exception
    shown = runner.invoke(app, ["show", "--verbose", "acme/widgets", "42"])
    assert shown.exit_code == 0, shown.exception
    assert "Provider: fixture" in shown.output
    assert "interpretation unverified" in shown.output
    assert "run() acquires a module-level lock around the working-directory lookup." in shown.output
    verbose = runner.invoke(app, ["show", "--verbose", "acme/widgets", "42"])
    assert "package-lock.json" in verbose.output


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres")
def test_ingest_cli_with_fake_http(database: str, monkeypatch: pytest.MonkeyPatch):
    import httpx

    from altiscope.ingest.github.pat import PatClient
    from tests.test_pat_client import api_payloads

    payloads = api_payloads()

    def client(token: str | None, *, base_url: str) -> PatClient:
        return PatClient(
            token,
            client=httpx.Client(
                base_url="https://api.github.com",
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json=payloads[request.url.path])
                ),
            ),
        )

    monkeypatch.setattr("altiscope.ingest.github.pat.PatClient", client)
    result = CliRunner().invoke(app, ["ingest", "owner/repo", "1"])
    assert result.exit_code == 0, result.exception
    assert "snapshot 1" in result.output
    payloads["/repos/owner/repo/pulls/1/files"] = []
    failed = CliRunner().invoke(app, ["ingest", "owner/repo", "1"])
    assert failed.exit_code == 1
    assert "incomplete" in failed.output
