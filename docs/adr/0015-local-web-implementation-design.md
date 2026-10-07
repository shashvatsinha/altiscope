# ADR-0015: Local web implementation design

Status: Accepted by the owner on 2026-10-06, including the five items under
"Owner decisions".

Issue: [#85](https://github.com/shashvatsinha/altiscope/issues/85), within
[M4 #7](https://github.com/shashvatsinha/altiscope/issues/7).

[ADR-0014](0014-local-web-and-hosted-access.md) settles the product scope: a local,
loopback-only web app using the owner's server-side GitHub token. This record settles
how to build it from the current code. It does not change ADR-0014, ADR-0010/0011/0012,
published prompts, or existing migrations.

## What the current code constrains

- `PatClient.get_repository_metadata` rejects any non-public repository, and
  `reconcile_repository` writes `visibility='public'` and never updates it. Private
  access is therefore new work, not a configuration change (#88).
- `resolve_reports` and `aggregate_reports` are synchronous, report no progress, and make
  provider calls with no spend check. PR reports and snapshots are already saved
  independently (`autocommit`), so an interrupted run keeps its completed work and a rerun
  resumes from it.
- `show-report` and `show-aggregate` hold inline SQL in the CLI. There is no read layer.
- `ModelSpec.input_usd_per_mtok` and `output_usd_per_mtok` default to `0`. A model with
  no configured price looks free, so a spend bound computed from prices would be wrong.
- `llm_calls.cost_usd` is null when usage or pricing is unavailable (`cost_status`).
- `docker-compose.yml` publishes Postgres on `5432:5432`, which is every interface.
- The checked-in demo repository uses the fixed synthetic id `9100000000000000`.

## Decision

### 1. Framework and layout

FastAPI served by uvicorn, Jinja2 server-rendered pages, and JSON under `/api/v1`. No
JavaScript build step. New runtime dependencies: `fastapi`, `uvicorn`, `jinja2`,
`python-multipart`. Routes are plain `def` so the existing synchronous psycopg and httpx
code runs in FastAPI's thread pool unchanged. Rejected: Flask (no typed request/response
models; the project already uses Pydantic), Django (its ORM and migrations would compete
with the numbered SQL migrations), a JavaScript single-page app (adds a build toolchain),
Streamlit (little control over accessibility and request protection).

```
src/altiscope/read/   view models and queries; no web imports; the CLI uses it too
src/altiscope/web/    app factory, security, routes, jobs, templates/, static/
```

`web/` contains no SQL and no vendor SDK imports; it calls `read/` and the existing
services. Pages are usable without JavaScript. One small static script may enhance
progress updates. A strict Content-Security-Policy (`default-src 'self'`, no inline
script or style, no CDN assets) is part of the contract.

### 2. Start and Postgres

`altiscope serve [--port 8765]` runs one uvicorn process (one worker, no reload). Host
defaults to `127.0.0.1`; `--host` accepts only `127.0.0.1` or `::1`, and anything else is
refused at startup. Startup verifies the database is reachable and migrations are current
and exits with the `altiscope db migrate` instruction otherwise; it never migrates
implicitly. Postgres comes from the existing Docker Compose service, with its host port
changed to `127.0.0.1:5432:5432` (#96). `GET /healthz` returns `200` with no details when
the database answers and `503` when it does not.

### 3. API and pages

JSON errors always use `{"error": {"code", "message", "request_id"}}` with a fixed
vocabulary of codes (`invalid_input`, `not_found`, `github_unauthorized`,
`github_not_accessible`, `github_rate_limited`, `github_unavailable`, `over_budget`,
`generation_disabled`, `generation_failed`, `internal`). Messages are written for
people; exception text and GitHub response bodies are never forwarded.

| Route | Purpose |
|---|---|
| `GET /` | saved repositories, token-accessible repositories, owner/name entry |
| `GET /repositories/{github_id}` | window and detail-level form; latest report; version history |
| `GET /reports/{aggregate_id}` | one exact aggregate: text, inputs, PR links |
| `GET /pr-reports/{id}` | one exact PR report: text, facts, exclusions, GitHub link |
| `GET /generations/{id}` | progress and outcome of one generation |
| `GET /api/v1/repositories`, `.../{github_id}/reports`, `/aggregates/{id}`, `/pr-reports/{id}` | read views of the same data |
| `GET /api/v1/github/repositories` | token-accessible list, cached in memory five minutes |
| `POST /api/v1/github/repositories/refresh`, `.../resolve` | refresh the list; resolve an owner/name |
| `POST /api/v1/generations`, `GET /api/v1/generations/{id}` | start and observe generation |

Repositories are addressed by GitHub's numeric id, not owner/name
([REPOSITORY-IDENTITY.md](../REPOSITORY-IDENTITY.md)). A `GET` never starts generation or calls a model provider; only
the token-accessible list may call GitHub, on a cache miss. HTML forms post to the same
endpoints and redirect (303) to the generation page.

### 4. Repository discovery and private access

Saved repositories come from the database and need neither network nor token. The
token-accessible list is `GET /user/repos` over the existing pagination rules. An
owner/name entry is validated with the existing `owner/name` pattern and resolved only
through `GET /repos/{owner}/{name}` on the configured API base; the app never fetches a
user-supplied URL.

Private repositories send source code to the configured model provider. That is a data
decision, so it is explicit: private ingestion is allowed only when
`ALTISCOPE_PRIVATE_REPOSITORIES=allow` is set (default off) and a token is present. The
pages show which provider and model will receive content before generation. The same
setting governs the CLI because both use `PatClient`. `reconcile_repository` records the
real visibility and updates it when it changes. The token needs read access to
repository metadata and pull requests; fine-grained, read-only tokens are recommended.

`GitHubAccessError(CollectionError)` carries a `kind` that maps one to one onto the API
codes above. GitHub returns 404 both for missing and for inaccessible private
repositories; the message says so rather than guessing. Saved reports stay readable when
GitHub access fails, labelled with when the repository was last refreshed.

### 5. Request protection and credentials

No login and no cookies, so the threats are other websites and DNS rebinding.

- Reject any request whose `Host` is not `127.0.0.1:<port>`, `localhost:<port>` or
  `[::1]:<port>` (400).
- Every non-`GET` request must carry an `Origin` equal to one of those hosts, must not
  have `Sec-Fetch-Site` other than `same-origin` or `none` when present, and must carry
  the per-process CSRF token (hidden form field or `X-Altiscope-CSRF`). A missing
  `Origin` is rejected.
- No CORS headers. Send `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store`, and `frame-ancestors 'none'`. External links use
  `rel="noopener noreferrer"`.
- Jinja autoescape stays on; no `|safe` on source-derived text. A test fails the build on
  any `|safe` or `autoescape` override.
- The token and provider keys are read only by server code. View models carry no
  credentials, raw model request/response payloads, or unrecorded assessor verdicts.
  Request logs hold method, route template, status, duration and request id: no query
  string, body, repository name or headers. Error responses use the fixed vocabulary.

### 6. Generation, progress and duplicates

`POST /api/v1/generations` accepts `{repository, since, until, altitude,
check_github, regenerate}`, validates it, and starts a job on a single background
worker thread, answering `202` with the job id. Opening a saved report never starts one.
Progress comes from a new optional `progress` callback accepted by `resolve_reports`,
`summarize` and `aggregate_reports`; the CLI passes none and its output is unchanged.
Phases: `listing`, `fetching n/N`, `summarizing n/N`, `aggregating`, then `done` or
`failed`. The page refreshes by polling every two seconds, and by a `meta refresh`
fallback when script is off; a polite live region announces phase changes.

Jobs live in memory. A duplicate request for the same repository id, window, detail
level and flags returns the running job. A Postgres session advisory lock on the
request key also stops a second `altiscope serve` from running it. The CLI is not
coordinated with the server. Closing the server abandons a running job: saved snapshots
and PR reports remain, any open spend reservation is marked abandoned, and rerunning
resumes from the cache. After a restart an old job URL answers "not running" and links to
the repository history. There is no cancel in M4; stop the server.

Result origin is derived per request and is not stored on any report: `saved` (existing
report returned, GitHub not checked), `generated` (new rows written; with call counts), or
`reused` (generation requested, zero model calls, existing reports matched by input
versions). A failed generation never replaces or hides the previous usable report.

### 7. Spend limits

Settings: `ALTISCOPE_GENERATION_ENABLED` (default `true`), `ALTISCOPE_SPEND_LIMIT_REQUEST_USD`
(default `2.00`), `ALTISCOPE_SPEND_LIMIT_DAY_USD` (default `10.00`, per UTC day). When
disabled, saved reports stay readable and generation answers `generation_disabled`.

Reservation is made per provider-call stage, after the cache check, so cache hits cost
nothing and never reserve:

1. Before PR reports: the upper bound for each missing report is estimated input tokens
   times the routed model's input price plus `reserved_output_tokens` times its output
   price, times the generator's attempt ceiling. The sum is shown to the user and reserved. The aggregate
   is not estimated yet because its inputs do not exist.
2. Before the aggregate: the same bound is computed for the actual tree from the real
   input texts and reserved separately. If it does not fit, the job stops with
   `over_budget`; the PR reports already saved stay and the user can open or retry them.

A reservation is refused unless both the per-request ceiling and the remaining day total
allow it. The check and insert run in one Postgres transaction under an advisory lock.
A model whose input and output prices are both `0` is refused unless the registry marks
it `free: true`; this closes the unpriced-model hole. After the stage, the reservation is
settled to the sum of its recorded call costs; if any call's cost is unavailable it
settles to the reserved bound, so the ledger never undercounts. The day total is the sum of
settled amounts and open reservations. New table `spend_reservations`: id, request key,
stage, reserved USD, settled USD, status (`open`, `settled`, `abandoned`), timestamps.
Open reservations from a previous process are marked `abandoned` at startup and count at
their reserved amount. The limit covers generation started from the web app only; CLI
runs are not counted. These are bounds on mistakes, not billing: provider-side limits
remain the real safeguard.

### 8. Fixtures and the saved/new/reused label

`altiscope fixtures load` stores the checked-in synthetic billing repository (id
`9100000000000000`, defined as one constant) in Postgres through the production
engine with the recorded provider, so no credential or paid call is needed. Repeating it
preserves history. Pages and API mark that exact repository as a fixture, not real
output. Real repositories never use that id.

### 9. Accessibility baseline

Every page lands with: one `<main>` and landmark regions, a skip link, one `h1`, labelled
controls, errors tied to fields by `aria-describedby` and announced, status in a live
region, visible focus, keyboard-only operation, no information by colour alone, WCAG AA
contrast, text resizing to 200%, and `prefers-reduced-motion`. Page tests parse the HTML
and assert these; #92 adds an audit and records anything automated tests cannot cover.

## Consequences

- #88 changes shared ingestion behavior: private repositories become ingestible
  from the CLI as well, behind the explicit setting.
- #86 creates `read/` and moves the inline SQL; CLI output parity tests protect it.
- #93 adds one migration (`spend_reservations`), the optional `free` registry flag, and
  guard hooks in `summarize` and `aggregate_reports`.
- #87 adds the four dependencies, `serve`, and request protection. #99 adds the job
  runner and `progress` callbacks. #96 narrows the Compose port.
- One process, one worker, in-memory jobs: simple, and deliberately not safe for
  several users. M5 replaces this with its own isolation design.

## Owner decisions

1. FastAPI plus Jinja, and the four dependencies.
2. Private ingestion off unless `ALTISCOPE_PRIVATE_REPOSITORIES=allow`.
3. Default limits: $2.00 per request, $10.00 per UTC day.
4. Web-only spend accounting (CLI runs not counted).
5. No cancel button in M4.
