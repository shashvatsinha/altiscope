from __future__ import annotations

from typing import Any

import httpx
import pytest

from altiscope.ingest.github.pat import CollectionError, PatClient


def test_pagination_and_token_stay_on_configured_host():
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request):
        requests.append(request)
        if request.url.params["page"] == "1":
            return httpx.Response(
                200,
                json=[{"id": 1}],
                headers={"link": '<https://evil.invalid/?page=2>; rel="next"'},
            )
        return httpx.Response(200, json=[{"id": 2}])

    with httpx.Client(
        base_url="https://api.github.com", transport=httpx.MockTransport(handle)
    ) as http:
        client = PatClient("secret", client=http)
        assert client._pages("/items") == [{"id": 1}, {"id": 2}]  # pyright: ignore[reportPrivateUsage]
    assert len(requests) == 2
    assert all(r.url.host == "api.github.com" for r in requests)
    assert requests[0].headers["Authorization"] == "Bearer secret"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_terminal_errors_are_safe_and_retries_bounded(status: int, monkeypatch: pytest.MonkeyPatch):
    def no_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("altiscope.ingest.github.pat.time.sleep", no_sleep)
    count = 0

    def handle(request: httpx.Request):
        nonlocal count
        count += 1
        return httpx.Response(status, json={"message": "secret must never be printed"})

    with (
        httpx.Client(
            base_url="https://api.github.com", transport=httpx.MockTransport(handle)
        ) as http,
        pytest.raises(CollectionError) as error,
    ):
        PatClient("secret", client=http).fetch_pull_request("owner/repo", 1)
    assert "secret" not in str(error.value)
    assert count == (3 if status in (429, 503) else 1)


def test_private_repository_is_rejected():
    with (
        httpx.Client(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"private": True})),
        ) as http,
        pytest.raises(CollectionError, match="public"),
    ):
        PatClient(None, client=http).fetch_pull_request("owner/repo", 1)


def api_payloads() -> dict[str, Any]:
    pr = {
        "id": 42,
        "number": 1,
        "title": "Add a file",
        "body": None,
        "user": {"login": "a"},
        "state": "closed",
        "merged": True,
        "draft": False,
        "base": {"ref": "main"},
        "head": {"ref": "feature", "sha": "abcdef1234567"},
        "merge_commit_sha": "abcdef1234567",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "closed_at": "2026-01-02T00:00:00Z",
        "merged_at": "2026-01-02T00:00:00Z",
        "additions": 1,
        "deletions": 0,
        "changed_files": 1,
        "commits": 1,
        "labels": [],
        "html_url": "https://github.com/owner/repo/pull/1",
    }
    return {
        "/repos/owner/repo": {"id": 123, "private": False, "default_branch": "main"},
        "/repos/owner/repo/pulls/1": pr,
        "/repos/owner/repo/pulls/1/files": [
            {"filename": "asset.bin", "status": "added", "additions": 1, "deletions": 0}
        ],
        "/repos/owner/repo/pulls/1/commits": [
            {"sha": "abcdef1234567", "commit": {"message": "Add file", "author": {}}}
        ],
        "/repos/owner/repo/pulls/1/reviews": [],
        "/repos/owner/repo/pulls/1/comments": [
            {"id": 5, "body": "inline", "created_at": "2026-01-01T01:00:00Z", "user": None}
        ],
        "/repos/owner/repo/issues/1/comments": [
            {"id": 5, "body": "conversation", "created_at": "2026-01-01T02:00:00Z", "user": None}
        ],
    }


def test_complete_collection_preserves_missing_patch_and_comment_identity():
    payloads = api_payloads()
    with httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payloads[request.url.path])
        ),
    ) as http:
        client = PatClient("secret", client=http)
        snapshot = client.fetch_pull_request("owner/repo", 1)
    assert snapshot.files[0].patch is None
    assert len(snapshot.comments) == 2
    assert snapshot.comments[0].kind != snapshot.comments[1].kind
    assert snapshot.body == ""
    assert set(client.raw) == {
        "repository",
        "pull_request",
        "files",
        "commits",
        "reviews",
        "inline_comments",
        "conversation_comments",
    }


def test_count_mismatch_fails_before_snapshot_creation():
    payloads = api_payloads()
    payloads["/repos/owner/repo/pulls/1/files"] = []
    with (
        httpx.Client(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payloads[request.url.path])
            ),
        ) as http,
        pytest.raises(CollectionError, match="counts disagree"),
    ):
        PatClient(None, client=http).fetch_pull_request("owner/repo", 1)
