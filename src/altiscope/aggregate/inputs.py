"""Exact report versions supplied to a model, recorded independently of its output.

The resolver selects PR report versions. Storage loads their text and PR links.
The aggregate service supplies saved child reports to each parent request.
An aggregate input carries all underlying PR links, including those not discussed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ReportInput:
    kind: Literal["pr", "aggregate"]
    report_version_id: str
    text: str
    pr_urls: tuple[str, ...]
    source_hash: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ("pr", "aggregate"):
            raise ValueError("Unknown report kind")
        if not self.report_version_id.strip() or not self.text.strip() or not self.pr_urls:
            raise ValueError("Report inputs require a version, text, and underlying PR links")
        if any(not url.strip() for url in self.pr_urls):
            raise ValueError("Underlying PR links must not be blank")


def render_inputs(instruction: str, inputs: tuple[ReportInput, ...]) -> str:
    """Render the same inputs that generation retains for later storage and drill-down."""
    if not inputs:
        raise ValueError("Nothing to aggregate")
    identities = [(item.kind, item.report_version_id) for item in inputs]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate input report version")
    # Database identities and navigation links are application data, not model tasks.
    reports = [{"report": i, "text": item.text} for i, item in enumerate(inputs, 1)]
    return instruction + "\n\nInput reports (data):\n" + json.dumps(reports, ensure_ascii=False)


def underlying_pr_urls(inputs: tuple[ReportInput, ...]) -> tuple[str, ...]:
    """Include every supplied PR link, in a stable order, without consulting model output."""
    return tuple(sorted({url for item in inputs for url in item.pr_urls}))
