"""Readable reports with deterministic drill-down and optional generation details."""

from __future__ import annotations

import json

from altiscope.aggregate.service import SavedAggregate

LABELS = {"ic": "Engineer", "manager": "Manager", "exec": "Executive"}


def render_aggregate(
    report: SavedAggregate, *, verbose: bool = False, navigation: bool = True
) -> str:
    lines = [
        f"{LABELS[report.query.altitude]} view — {report.query.repository}",
        f"{report.query.since.date()} through {report.query.until.date()}",
        f"Underlying PRs: {len(report.pr_urls)}",
        "",
    ]
    if report.output is None:
        lines.extend(["Generation failed; earlier reports remain available.", *report.errors])
    else:
        lines.extend([report.output.headline, "", report.output.narrative, ""])
        for section in report.output.sections:
            lines.extend([section.heading, section.text, ""])
    lines.append("Underlying PRs:")
    lines.extend(f"  {url}" for url in report.pr_urls)
    if navigation:
        lines.extend(["", "Input reports (exact versions):"])
        for item in report.inputs:
            command = "show-report" if item.kind == "pr" else "show-aggregate"
            lines.append(f"  altiscope {command} {item.report_version_id}")
    if verbose:
        lines.extend(
            [
                "",
                f"Report: {report.id}",
                f"Generated: {report.created_at.isoformat()}",
                f"Provider: {report.provider}; model: {report.model_id}",
                f"Prompt: {report.prompt_version}; hash: {report.prompt_hash}",
                f"Input hash: {report.input_hash}",
                "Generation settings:",
                json.dumps(report.settings, indent=2, sort_keys=True),
                "Exact prompt file:",
                report.prompt_source,
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
