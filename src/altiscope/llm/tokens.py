"""Token estimation for planning.

Routing and planning need a size estimate before a provider is chosen. The provider's
own `count_tokens` is authoritative and should be used once a model is picked; this
heuristic deliberately overestimates so that plans err toward smaller inputs.
"""

from __future__ import annotations

import math

# Claude tokenizers average roughly 3.5 characters per token on English prose and closer
# to 3 on code and diffs. Diffs dominate our inputs, so use 3 and round up.
_CHARS_PER_TOKEN = 3.0


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / _CHARS_PER_TOKEN)
