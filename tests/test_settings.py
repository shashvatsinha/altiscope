from pathlib import Path

from altiscope.config import Settings


def test_blank_optional_settings_from_example_are_ignored(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("ALTISCOPE_GITHUB_APP_ID=\nALTISCOPE_GITHUB_TOKEN=\n")
    settings = Settings(_env_file=path)  # pyright: ignore[reportCallIssue]
    assert settings.github_app_id is None
    assert settings.github_token is None
