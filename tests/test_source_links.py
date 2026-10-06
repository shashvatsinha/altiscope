from altiscope.store.source_links import historical_repository_locator, snapshot_html_url


def test_blank_or_missing_html_url_is_no_link():
    assert snapshot_html_url({"html_url": "https://github.com/o/r/pull/1"}) == (
        "https://github.com/o/r/pull/1"
    )
    assert snapshot_html_url({"html_url": ""}) is None
    assert snapshot_html_url({"html_url": "  "}) is None
    assert snapshot_html_url({}) is None
    assert snapshot_html_url(None) is None


def test_repository_locator_prefers_snapshot_then_pr_urls_then_current():
    docs = {"inputs": [{"pr_urls": ["https://github.com/o/r/pull/9"]}]}
    assert (
        historical_repository_locator("cur/rent", docs, {"repository": "snap/shot"}) == "snap/shot"
    )
    assert historical_repository_locator("cur/rent", docs, {"repository": " "}) == "o/r"
    assert historical_repository_locator("cur/rent", {}, None) == "cur/rent"
