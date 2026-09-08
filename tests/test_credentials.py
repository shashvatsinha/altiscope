from pathlib import Path

import pytest

from altiscope.llm.credentials import api_key


def test_environment_overrides_local_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / ".env"
    path.write_text("MODEL_TEST_KEY=file-value\n")
    monkeypatch.delenv("MODEL_TEST_KEY", raising=False)
    assert api_key("MODEL_TEST_KEY", path) == "file-value"
    monkeypatch.setenv("MODEL_TEST_KEY", "env-value")
    assert api_key("MODEL_TEST_KEY", path) == "env-value"
    assert api_key(None, path) is None
