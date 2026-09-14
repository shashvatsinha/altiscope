"""Reveal-safe rendering shared by review and later comparison inspection."""

from __future__ import annotations

import json

from altiscope.store.comparisons import ComparisonSource, StoredResult


def render_frozen_source(source: ComparisonSource) -> str:
    """Render the exact saved evidence and historical navigation owned by code."""
    lines = [
        f"Frozen source {source.id} ({source.kind}; hash {source.content_hash})",
        "Historical source links:",
    ]
    links: list[str] = []
    if source.kind == "pr":
        snapshot = source.preparation_document.get("snapshot")
        if isinstance(snapshot, dict):
            url = snapshot.get("html_url")
            if isinstance(url, str):
                links.append(url)
    else:
        links.extend(url for item in source.inputs for url in item.pr_urls)
    lines.extend(f"  {url}" for url in dict.fromkeys(links))
    lines.extend(
        [
            "Preparation and omissions:",
            json.dumps(source.preparation_document, indent=2, sort_keys=True),
            "Exact prepared source text:",
            source.prepared_text,
        ]
    )
    return "\n".join(lines) + "\n"


def render_review_result(result: StoredResult) -> str:
    """Render only the exact target result, without recipe/model labels or assessment output."""
    if result.status != "succeeded" or result.output is None:
        raise ValueError("human review requires a successful exact result")
    return (
        f"Generated result {result.id} (immutable output hash {result.output_hash})\n"
        + json.dumps(result.output, indent=2, sort_keys=True)
        + "\n"
    )
