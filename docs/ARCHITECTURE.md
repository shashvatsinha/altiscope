# Altiscope architecture

Status: **proposal, v0.** Nothing here has been validated against real usage yet.
This document is the thing to argue with before the implementation grows. Decisions that
are already firm enough to have a rationale are recorded as ADRs in `docs/adr/`.

## 1. What the system is

Altiscope reads merged pull requests from GitHub, produces one faithful structured
summary per PR, and on demand composes those into views for any level of an engineering
organization over any date range. Every sentence a reader sees can be traced, through
database rows rather than prose, to the pull requests that justify it.

Three properties, in priority order:

1. **Accuracy.** A wrong summary that reaches a director is misinformation with
   false authority. The system prefers saying less, saying "I could not determine
   this", and exposing what it did *not* read, over a fluent guess.
2. **Provenance as data.** Claims and their sources are rows and foreign keys, not
   footnotes. Anyone can drill from a quarterly narrative to a hunk of a diff.
3. **Reader-appropriate altitude.** The same underlying facts are presented at the
   level of detail the reader needs, chosen per query, never pre-computed on a
   calendar.

## 2. The pipeline at a glance

```
GitHub ──(App / PAT, REST+GraphQL)──▶ ingest ──▶ PR snapshot tables (immutable)
                                                       │
                                        deterministic facts + diff policy
                                                       │
                                                       ▼
                                          atomic summarize (LLM, once per PR)
                                                       │
                                     structured claims + evidence pointers
                                                       │
                                            verify (second model, per claim)
                                                       │
                                                       ▼
   query {subject, window, altitude} ──▶ aggregate (LLM, on demand, reduction tree)
                                                       │
                                aggregate claims → sources (pr_claims | child aggregate claims)
                                                       │
                                                       ▼
                                          coverage report + drill-down UI/API
                                                       │
                                      human flags → eval set → prompt/model regression
```

Two distinct LLM stages, plus an optional third:

| Stage | Input | Output | Runs |
|---|---|---|---|
| `pr_summary` | One PR: description, full filtered diff, review threads, commits, computed facts | `PrSummary` with `Claim[]`, each with `Evidence[]` | Once per merged PR, cached until invalidated |
| `aggregate` | N `PrSummary` rows (or N child aggregates) + the query | `AggregateSummary` with `AggregateClaim[]`, each citing source claim ids | On demand, per query; result cached by input-set hash |
| `verify` | One claim + the PR material it cites | verdict: supported / partially / unsupported / cannot_determine | Once per atomic claim (default on); on demand for aggregates |

## 3. Ingestion

**Source of truth is a stored snapshot, not the live API.** Every PR is fetched once at
merge (plus a reconciliation pass) and written to append-only tables: `pull_requests`,
`pr_files` (with patch text), `pr_reviews`, `pr_comments`, `pr_commits`. Summaries are
computed from the snapshot, so a summary is reproducible and its evidence pointers stay
valid even if GitHub later loses the data or the repo is deleted.

**Auth.** A GitHub App installation is the supported path for organizations:
fine-grained permissions (`pull_requests:read`, `contents:read`, `members:read`),
short-lived installation tokens, an audit trail on GitHub's side, and it works on
GitHub Enterprise Server. A personal access token is accepted for single-user evaluation
and clearly labelled as such. See ADR-0006.

**Mechanism.** Polling with cursors is the baseline because it always works (no inbound
network path required). Webhooks (`pull_request.closed` with `merged=true`) are an
optimization layered on later for freshness; they never replace reconciliation.

**What is ingested.** All PRs (open, closed, merged) are recorded so that counts are
honest, but only *merged* PRs are summarized in v1. See ADR-0003 for the argument and
the open question about open/abandoned work.

**Diff policy.** The principle is "read the full diff", and the failure mode of that
principle is a 40,000-line lockfile or a vendored dependency. A deterministic policy
(`altiscope.ingest.diff_policy`) classifies each file as `included` or `excluded` with a
reason (`lockfile`, `generated`, `vendored`, `binary`, `minified`, `oversize`). Excluded
files still contribute to computed facts (counts, additions/deletions) and the exclusion
list is part of the summary's `input_manifest`, shown to the model *and* to the reader:
"This summary did not read 3 generated files (12,400 lines)". The model is never
silently shown a partial PR.

## 4. Atomic summaries

The output schema (`altiscope.schemas.pr_summary`) is deliberately not free prose:

- `headline`: one sentence, what changed.
- `claims[]`: each an atomic, checkable statement with a `kind`
  (feature, bugfix, refactor, infra, test, docs, perf, security, dependency, chore)
  and `evidence[]` pointing at a file path (optionally hunk), a quoted span of the PR
  description, a review comment id, or a commit sha. A claim with no evidence is
  rejected at validation time.
- `description_vs_diff`: discrepancies between what the PR description says and what the
  diff actually does. PR descriptions are a primary source of drift in
  human-written status reports; a summarizer that trusts them uncritically inherits it.
- `uncertainties[]`: things the model could not determine from the material.
- `narrative`: a short paragraph, for readers, composed only from the claims above.

Numbers are never the model's job. `facts` (files, additions, deletions, languages,
test files touched, reviewers, review rounds, time to merge, linked issues) are computed
in code from the snapshot and stored separately. The model receives them as context.
The UI renders them from data, so a summary cannot misquote a number.

Validation after generation, before storage: every evidence path must exist in
`pr_files`; every quoted description span must be a substring of the body; every
comment id must exist. Failures are repaired with one constrained retry, then the summary
is stored with status `needs_review` rather than published.

Cache invalidation: a `pr_summary` row is keyed by `(pr_id, prompt_version_id,
schema_version, model_id)`. Changing any of these produces a new row; the previous one is
kept with `is_current = false` so model/prompt quality can be compared on the same PR.
See principle 2 and ADR-0005.

## 5. Aggregation at query time

A query is `{subjects, window, altitude, lens}`:

- `subjects`: one or more people, teams, or repositories. Team membership is temporal
  (`team_memberships.valid_from/valid_to`), resolved as of each PR's merge date, because
  "the team's Q2" must not silently include work someone did on their previous team.
- `window`: any `[start, end)`; nothing is pinned to weeks or quarters.
- `altitude`: `ic | lead | manager | director | exec`. Altitude controls prompt
  variant, target length, and how many source claims a single aggregate claim is
  expected to rest on. It never changes the provenance rules.
- `lens` (later): themes such as reliability or security, mapping to claim kinds.

**Input set.** The atomic summaries whose PRs merged in the window and match the
subjects. The set is recorded in `aggregate_inputs`, so coverage is a query, not a
guess.

**Reduction tree.** Principle 3 forbids pre-computed rollups; it does not forbid
query-time intermediates. When the input set exceeds the routed model's budget, the
planner (`altiscope.aggregate.planner`) partitions inputs, produces child aggregates,
and synthesizes the parent from the children. Each child is a stored aggregate with
its own claims and sources, so drill-down works at every level:
parent claim → child claim → pr claim → file/hunk. Partitioning is deterministic
(by merge time, then by subject) so the same query yields the same tree.

**Provenance enforcement.** The model outputs `sources: [claim_id, ...]` per aggregate
claim; ids are opaque short tokens issued by the system per call, so the model cannot
invent a plausible-looking id. Any id not in the input set fails validation. An aggregate
claim with no sources is dropped, and the drop is recorded.

**Coverage, the defence against selective emphasis.** For every aggregate the system
computes and stores which input PRs are cited by at least one claim and which are not.
The uncited list is shown alongside the narrative with each PR's headline and size.
A reader can see at a glance that "the team shipped the new billing flow" is true and
that the eleven PRs of migration work went unmentioned. Coverage below a configurable
threshold marks the aggregate `low_coverage`.

**Caching.** An aggregate is cached by hash of (sorted input pr_summary ids, altitude,
lens, prompt_version, model). Same question, same inputs, same answer. This is a cache
of an on-demand result, not a scheduled rollup; nothing is computed before it is asked
for.

**Language constraints.** Aggregates describe work, not people. Prompts forbid
evaluative language about individuals (productive, slow, struggled). Cross-developer
comparison views are rendered side by side from each person's own aggregate and
facts; the model is not asked to compare people. See ADR-0007 and the open question in
§10.

## 6. Model routing

`config/models.yaml` is the registry: models with provider, context window, output
limit, and cost; and per-stage routing with a default, an ordered list of candidates,
and an effort level. The router (`altiscope.llm.router`) picks the first candidate whose
usable context fits the input plus reserved output, and returns a `RoutingDecision`
with a human-readable `reason` ("default for stage", "input 410k tokens exceeds
claude-haiku-4-5 200k; escalated to claude-opus-5"). The decision, model id, provider,
prompt version, effort, token counts, latency and request id are stored on `llm_calls`
and referenced by every summary. Verification can require a model different from the
producer.

Providers implement one small protocol (`generate_structured`, `count_tokens`). The
Anthropic adapter is first. OpenAI-compatible, Bedrock, Vertex and Foundry adapters are
expected; enterprises frequently mandate one. See ADR-0005.

## 7. Verification and feedback

- **Automated verification** runs a second model (registry-enforced to differ from the
  producer) over each atomic claim with the cited evidence and the surrounding diff, and
  stores a verdict. Cost is roughly a second summarization per PR, incurred once.
  Default on for atomic summaries; on demand for aggregates.
- **Human flags** are first-class rows (`flags`) on any claim, with a category:
  `factual_error`, `overstated`, `understated`, `omission`, `misattribution`,
  `selective_emphasis`, `other`, plus free text. Flags are visible on the claim wherever it
  is rendered, and propagate upward: an aggregate claim whose sources carry open flags is
  marked.
- **Evaluation set.** Flagged and human-corrected claims become the regression set.
  A prompt or model change is measured against it before it becomes the default. Prompts
  are versioned files with content hashes recorded on every call.

## 8. Storage

Postgres only (ADR-0002). Migrations are plain SQL under `migrations/`, applied by a small
runner; the schema is the provenance contract and is meant to be read as SQL.
`migrations/0001_initial.sql` is the current data model. Highlights:

- Snapshot tables are append-only. Re-fetching a PR writes a new snapshot version;
  summaries reference the snapshot version they read.
- `pr_claim_evidence`, `aggregate_claim_sources`, `verifications`, `flags` are the
  provenance and feedback tables. Polymorphic references use nullable foreign key
  columns with a `CHECK` that exactly one is set, so referential integrity is enforced
  by the database.
- `llm_calls` stores routing and usage for every call. Full request/response payloads are
  stored by default for reproducibility and can be reduced to hashes for deployments
  where storing diffs twice is unacceptable.
- Background work (ingestion, summarization, verification) uses a Postgres job table with
  `SELECT ... FOR UPDATE SKIP LOCKED`. PRs merge at human pace; a second queue system is
  not justified.

## 9. Deployment, auth, and trust boundary

- One container image, two roles: `altiscope serve` (API + UI) and `altiscope worker`.
  Plus Postgres. That is the whole deployment.
- Nothing leaves the deployment except calls to the configured LLM provider and GitHub.
  Enterprises choose the provider (first-party API, Bedrock, Vertex, Foundry, or a
  compatible gateway); the registry makes that a config change.
- UI/API authentication: OIDC for SSO, GitHub OAuth for small orgs. Authorization
  baseline mirrors GitHub: you can read a summary if you can read the repository. Roles
  above that (org admin, team lead views) are additive. The permission check is a single
  function at the API boundary from the first commit, so it cannot be forgotten later.
- Audit log of who viewed what and who flagged what.

## 10. Open questions for the owner

These change what gets built and I have not resolved them alone:

1. **Open and abandoned PRs.** Merged-only summaries make in-flight work invisible; a
   manager asking "what is X working on" sees nothing until merge. Proposal: ingest all,
   summarize merged only, show open/abandoned as facts (counts, ages, titles). Summarizing
   open PRs later is possible but breaks "one-time event" caching.
2. **Cross-developer comparison.** The brief lists it as a view. I recommend it be
   side-by-side, not model-generated comparative judgment, because that surface is where
   an LLM summary most easily becomes a performance verdict. Please confirm or overrule.
3. **Payload retention.** Storing full prompts (which contain diffs) doubles stored
   source code. Default full, with a hashes-only mode; is that acceptable for the
   enterprise profile you have in mind?
4. **UI.** Proposal is server-rendered HTML with HTMX for v1 so the repo stays one
   language while the hard problems are solved; a richer front end can consume the same
   JSON API later. This is the most reversible decision here.
5. **Verification default.** Second-model verification on every atomic summary roughly
   doubles per-PR cost. I have it default-on because accuracy is priority one.

## 11. What is deliberately not built

- Retrieval or embedding search over PR content. Each PR is bounded and is read whole.
- Commit-level summaries.
- Scheduled rollups.
- Any code quality, security or compliance analysis. The `analyses`-style shape
  (claims with evidence against a PR snapshot) is chosen so that a future "finding"
  is the same kind of row as a claim, but no such stage exists.
