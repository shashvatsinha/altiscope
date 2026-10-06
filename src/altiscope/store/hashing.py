"""One canonical serialization and digest for content-addressed store records."""

from __future__ import annotations

import hashlib
import json


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_json(value: object) -> str:
    return hash_text(canonical_json(value))
