"""Bounded public-PR collection using a personal access token."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from altiscope.ingest.snapshot import PullRequestSnapshot


class CollectionError(RuntimeError):
    """Collection is incomplete; do not save or summarize its partial result."""


class PatClient:
    def __init__(
        self,
        token: str | None,
        *,
        base_url: str = "https://api.github.com",
        client: httpx.Client | None = None,
    ) -> None:
        self.client = client or httpx.Client(base_url=base_url, timeout=30)
        self.headers = {"Accept": "application/vnd.github+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.raw: dict[str, Any] = {}
        self.repository_metadata: dict[str, Any] = {}

    def close(self) -> None:
        self.client.close()

    def _get(self, path: str, page: int | None = None) -> httpx.Response:
        url = httpx.URL(path)
        if page is not None:
            url = url.copy_merge_params({"per_page": 100, "page": page})
        for attempt in range(3):
            try:
                response = self.client.get(
                    url,
                    headers=self.headers,
                    follow_redirects=False,
                )
            except httpx.TransportError:
                if attempt == 2:
                    raise CollectionError("GitHub transport failed after bounded retries") from None
                time.sleep(0.25 * (attempt + 1))
                continue
            if response.is_success:
                return response
            if response.status_code in (301, 302, 307, 308):
                target = response.url.join(response.headers.get("location", ""))
                if (target.scheme, target.host, target.port) != (
                    response.url.scheme,
                    response.url.host,
                    response.url.port,
                ):
                    raise CollectionError("GitHub redirected outside the configured API origin")
                url = target
                continue
            transient = response.status_code in (429, 500, 502, 503, 504) or (
                response.status_code == 403
                and (
                    response.headers.get("x-ratelimit-remaining") == "0"
                    or "retry-after" in response.headers
                )
            )
            if not transient or attempt == 2:
                raise CollectionError(f"GitHub HTTP {response.status_code}; collection not saved")
            try:
                delay = float(response.headers.get("retry-after", "1"))
            except ValueError:
                delay = 1
            if delay > 5:
                raise CollectionError("GitHub rate limited; retry ingestion later")
            time.sleep(max(0, delay))
        raise CollectionError("GitHub collection failed")

    def _pages(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, 101):
            response = self._get(path, page)
            batch = response.json()
            if not isinstance(batch, list):
                raise CollectionError("Unexpected GitHub collection response")
            items.extend(batch)
            if "next" not in response.links:
                return items
        raise CollectionError("Pagination limit reached; collection is incomplete")

    def get_repository_metadata(self, repository: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise CollectionError("Expected owner/repository")
        root = f"/repos/{repository}"
        repo = self._get(root).json()
        if repo.get("private") or repo.get("visibility", "public") != "public":
            raise CollectionError("Ingestion supports public repositories only")
        if not isinstance(repo.get("id"), int) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo.get("full_name", "")
        ):
            raise CollectionError("GitHub response lacks canonical repository identity")
        self.repository_metadata = repo
        return repo

    def list_merged_pull_requests(
        self, repository: str, since: datetime, until: datetime
    ) -> list[int]:
        since_utc = since if since.tzinfo is not None else since.replace(tzinfo=UTC)
        until_utc = until if until.tzinfo is not None else until.replace(tzinfo=UTC)
        if until_utc < since_utc:
            raise ValueError("until must be greater than or equal to since")

        repo = self.get_repository_metadata(repository)
        root = f"/repos/{repo['full_name']}"
        merged_numbers: list[tuple[datetime, int]] = []
        for page in range(1, 101):
            response = self._get(
                f"{root}/pulls?state=closed&sort=updated&direction=desc", page=page
            )
            batch = response.json()
            if not isinstance(batch, list):
                raise CollectionError("Unexpected GitHub collection response")
            if not batch:
                break
            for item in batch:
                updated_at_raw = item.get("updated_at")
                if updated_at_raw:
                    updated_at = datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
                    if updated_at < since_utc:
                        return list(dict.fromkeys(num for _, num in sorted(merged_numbers)))

                merged_at_raw = item.get("merged_at")
                if merged_at_raw:
                    merged_at = datetime.fromisoformat(merged_at_raw.replace("Z", "+00:00"))
                    if since_utc <= merged_at <= until_utc:
                        merged_numbers.append((merged_at, int(item["number"])))

            if "next" not in response.links:
                break
        else:
            raise CollectionError("Pagination limit reached; collection is incomplete")

        return list(dict.fromkeys(num for _, num in sorted(merged_numbers)))

    def fetch_pull_request(self, repository: str, number: int) -> PullRequestSnapshot:
        if number < 1:
            raise CollectionError("Expected positive PR number")
        repo = self.get_repository_metadata(repository)
        root = f"/repos/{repo['full_name']}"
        path = f"{root}/pulls/{number}"
        pr = self._get(path).json()
        files = self._pages(path + "/files")
        commits = self._pages(path + "/commits")
        reviews = self._pages(path + "/reviews")
        inline = self._pages(path + "/comments")
        conversation = self._pages(f"{root}/issues/{number}/comments")
        if len(files) != pr["changed_files"] or len(commits) != pr["commits"]:
            raise CollectionError("GitHub file/commit counts disagree; collection is incomplete")
        if len({f["filename"] for f in files}) != len(files):
            raise CollectionError("Duplicate files across pages; retry collection")
        # Detect a moving PR while collecting paginated records.
        refreshed = self._get(path).json()
        if (
            refreshed["updated_at"] != pr["updated_at"]
            or refreshed["head"]["sha"] != pr["head"]["sha"]
        ):
            raise CollectionError("PR changed during collection; retry ingestion")
        self.raw = dict(
            repository=repo,
            pull_request=pr,
            files=files,
            commits=commits,
            reviews=reviews,
            inline_comments=inline,
            conversation_comments=conversation,
        )
        fields = {
            key: pr.get(key)
            for key in (
                "number",
                "title",
                "body",
                "merge_commit_sha",
                "created_at",
                "updated_at",
                "closed_at",
                "merged_at",
                "additions",
                "deletions",
                "changed_files",
                "html_url",
            )
        }
        fields.update(
            repository=repo["full_name"],
            github_id=pr["id"],
            body=pr.get("body") or "",
            author_login=_login(pr),
            state="merged" if pr["merged"] else pr["state"],
            is_draft=pr.get("draft", False),
            base_ref=pr["base"]["ref"],
            head_ref=pr["head"]["ref"],
            merged_by_login=(pr.get("merged_by") or {}).get("login"),
            labels=[label["name"] for label in pr["labels"]],
            files=[
                dict(
                    path=f["filename"],
                    previous_path=f.get("previous_filename"),
                    status=f["status"],
                    additions=f["additions"],
                    deletions=f["deletions"],
                    patch=f.get("patch"),
                )
                for f in files
            ],
            commits=[
                dict(
                    sha=c["sha"],
                    message=c["commit"]["message"],
                    author_login=(c.get("author") or {}).get("login"),
                    authored_at=c["commit"]["author"].get("date"),
                )
                for c in commits
            ],
            reviews=[
                dict(
                    github_id=r["id"],
                    author_login=_login(r),
                    state=r["state"],
                    body=r.get("body") or "",
                    submitted_at=r.get("submitted_at"),
                )
                for r in reviews
            ],
            comments=[
                dict(
                    github_id=c["id"],
                    kind=kind,
                    author_login=_login(c),
                    body=c.get("body") or "",
                    created_at=c["created_at"],
                    path=c.get("path"),
                    line=c.get("line"),
                    in_reply_to_github_id=c.get("in_reply_to_id"),
                )
                for kind, batch in [("review", inline), ("issue", conversation)]
                for c in batch
            ],
        )
        return PullRequestSnapshot.model_validate(fields)


def _login(record: dict[str, Any]) -> str:
    return (record.get("user") or {}).get("login") or "[deleted]"
