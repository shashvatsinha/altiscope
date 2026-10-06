"""The one place that reads historical PR links out of a frozen snapshot."""

from __future__ import annotations

from collections.abc import Mapping


def snapshot_html_url(snapshot: Mapping[str, object] | None) -> str | None:
    """The PR's recorded web link; a blank value is treated as no link."""
    if not isinstance(snapshot, Mapping):
        return None
    url = snapshot.get("html_url")
    return url if isinstance(url, str) and url.strip() else None


def historical_repository_locator(
    current: str,
    preparation_document: Mapping[str, object],
    snapshot: Mapping[str, object] | None,
) -> str:
    """owner/repo as recorded when the source was frozen, falling back to ``current``."""
    if isinstance(snapshot, Mapping):
        locator = snapshot.get("repository")
        if isinstance(locator, str) and locator.strip():
            return locator
    inputs = preparation_document.get("inputs")
    if isinstance(inputs, list):
        for item in inputs:
            if not isinstance(item, dict):
                continue
            urls = item.get("pr_urls")
            if not isinstance(urls, list):
                continue
            for url in urls:
                if isinstance(url, str) and url.startswith("https://github.com/"):
                    parts = url.removeprefix("https://github.com/").split("/")
                    if len(parts) >= 2:
                        return "/".join(parts[:2])
    return current
