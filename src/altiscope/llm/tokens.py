"""Estimate tokens from character count for routing and planning.

The estimate can be too low or too high. Use a provider's token-count endpoint where
available, accounting for all parts of the request.
"""

from __future__ import annotations

import math

# Approximate one token per three characters, rounded up. This is not an upper bound.
_CHARS_PER_TOKEN = 3.0


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / _CHARS_PER_TOKEN)
