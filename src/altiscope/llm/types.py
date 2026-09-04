from __future__ import annotations

from typing import Literal

Stage = Literal["pr_summary", "aggregate", "verify"]
STAGES: tuple[Stage, ...] = ("pr_summary", "aggregate", "verify")

Effort = Literal["low", "medium", "high", "xhigh", "max"]
