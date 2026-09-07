# ADR-0006: Use a GitHub App for organization access

Status: proposed

## Context

Collection needs access to pull requests, diffs, comments, and team membership across
repositories on GitHub and GitHub Enterprise Server. Organization access should be
managed independently of an individual employee's account.

## Decision

- Use an organization-installed GitHub App with limited permissions and short-lived
  installation tokens as the primary identity.
- Support personal access tokens for evaluation and individual use. Identify this mode
  in the UI and logs.
- Poll with a cursor per repository. Add webhooks for faster updates while retaining
  periodic reconciliation to recover missed events.
- Save fetched material as immutable snapshots with fetch timestamps. Each summary
  references the snapshot it used.

## Consequences

- Organization setup would require installing and configuring the app, including its
  installation ID and credentials.
- GitHub Enterprise Server needs a configurable base URL and compatibility testing.
- Handle rate limits and backoff in the client. Run large backfills as background jobs.

The GitHub client interface exists. Authentication, fetching, snapshot storage, and
background collection remain unbuilt.
