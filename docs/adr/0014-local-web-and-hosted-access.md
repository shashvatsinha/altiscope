# ADR-0014: Deliver local web use before hosted repository connections

Status: Accepted by the owner on 2026-10-06 in the roadmap discussion.

Issues: [M4 #7](https://github.com/shashvatsinha/altiscope/issues/7),
[M5 #8](https://github.com/shashvatsinha/altiscope/issues/8).

## Context

The owner accepted the CLI manager reports and wants to use them through a web UI.
Altiscope's purpose is to explain what teams built in simple language grounded in
code changes. It need not know the desired direction or judge alignment. The prior
M4 plan bundled a hosted public demo, anonymous-generation controls, expert-review
pages, and a release-blocking study before routine private-repository use.

## Decision

M4 delivers a local web application on the owner's laptop or desktop, bound to
localhost with no sign-in or public access. Select a repository, date range, and
engineer/manager/executive detail level; generate or read the existing reports;
navigate exact contributing report versions and original GitHub PRs.

Use the owner's server-side GitHub token for permitted public and private repositories.
Support discovery or owner/name entry, not just preseeded repositories. Verify private
access and handle missing permissions without exposing credentials. Keep secrets out
of browser responses and logs. Protect local state-changing requests against cross-site
requests and validate Host/Origin. Reuse cost records and bounded generation requests.

M5 delivers a public-facing server with login and user-authorized repository access
through a GitHub App. A demo visitor can connect selected private repositories.
Authorization must cover caches, historical versions, recursive inputs, and navigation;
revocation and user isolation are required before public deployment. Broader temporal
team membership and scheduled refresh are follow-ups.

Expert-review UI #95 and qualified study #97 are deferred, remain open, and are not
M4 or M5 release gates. Feedback #94 is optional for M4. No public-demo allowlist,
anonymous visitor limits, or mandatory curated-publication storage is needed in M4.
The framework, rendering, local execution, and detailed budget policy are implementation
design work in #85; this ADR does not claim those choices are already settled.

## Supersession and preserved contracts

This decision supersedes the M4 study scheduling and release-gate requirements in
the roadmap and #7/#97, and any reading of ADR-0013 that requires the qualified study
before product delivery. ADR-0013's M3 workflow-only evidence boundary remains intact.
ADR-0010/0011/0012 provenance, immutable history, provider neutrality, versioned
prompts, and append-only migrations remain in force. Published prompts and historical
evaluation protocols/datasets are unchanged. No quality or effort-saving claim follows
from shipping the UI. A later study still requires qualified reviewers, newly versioned
protocol/data, fresh held-out cases, and real judgments.

## Consequences

M4 release acceptance is the owner completing the local web workflow, documented setup,
API/UI and accessibility checks, bounded generation, error/empty states, and accurate
source navigation. It includes a fixture path with no paid calls and a permission-aware
private-repository walkthrough using the owner's configured credentials. No private
source or report text is committed as release evidence. M5 accepts hosted login,
repository connections, isolation, revocation, and deployment checks.
