# ADR-0006: GitHub App as the primary ingestion identity

Status: proposed

## Context

Ingestion needs to read PRs, diffs, review comments and team membership across many
repositories, on github.com and GitHub Enterprise Server, under an identity an
enterprise security team will approve.

## Decision

- A GitHub App installed on the organization is the supported identity: least-privilege
  permissions, installation tokens that expire in an hour, an audit trail on GitHub's
  side, and no dependence on a human's account.
- A personal access token is supported for evaluation and single-user use, labelled as
  such in the UI and logs.
- Polling with per-repository cursors is the baseline. Webhooks are added for freshness
  and never trusted as the only source; a reconciliation pass catches missed events.
- Everything fetched is stored as an immutable snapshot with a fetch timestamp. Summaries
  reference the snapshot they read.

## Consequences

- Setup for an organization is "install the app, paste the installation id", which is
  what enterprise admins expect.
- GHES support is a base-URL setting.
- Rate limits are handled centrally in the client with backoff; backfilling a large org
  is a background job, not an interactive command.
