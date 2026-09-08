"""Resolve only a provider's configured key; never log or persist its value."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


def api_key(name: str | None, env_file: Path = Path(".env")) -> str | None:
    if name is None:
        return None
    if name in os.environ:
        return os.environ[name]
    return dotenv_values(env_file).get(name)
