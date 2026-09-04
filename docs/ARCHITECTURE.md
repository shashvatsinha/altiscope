# Architecture

[`THESIS.md`](../THESIS.md) describes the problem Altiscope addresses and the hypotheses
behind it. This document describes the proposed implementation: the pipeline stages, the
data model, what is checked where, and the tradeoffs each choice makes. Individual
decisions and their rejected alternatives are recorded in [`adr/`](adr/).

The framing that matters for reading what follows: models occupy three bounded steps
inside a chain that is otherwise deterministic. Source material is stored before it is
interpreted, numbers are computed in code, model output is a typed structure whose
pointers are checked against that stored material, and the reader receives claims with
their evidence attached rather than prose with citations appended.

## 1. Status

Status: proposal, v0, with a tested foundation. Nothing has been validated against real
usage; there is no golden set and no evaluation loop, so no claim about output quality in
this repository has been tested.

| Component | Status |
|---|---|
| Postgres schema (`migrations/0001_initial.sql`) | implemented; applied and constraint-tested against Postgres in CI |
| Migration runner (`store/migrate.py`) | implemented |
| Diff policy (`ingest/diff_policy.py`) | implemented and tested |
| Snapshot types (`ingest/snapshot.py`) | implemented as pydantic models |
| GitHub client | interface only (`ingest/github/client.py` is a `Protocol`); no implementation |
| Snapshot write path | not built |
| Fact computation (`summarize/facts.py`) | implemented and tested |
| Prompt context assembly (`summarize/context.py`) | implemented and tested |
| Evidence validation (`summarize/validate.py`) | implemented and tested |
| `pr_summary` orchestration (call, retry, store) | not built |
| Verification (`verify/`) | schema and prompt only; no implementation |
| Reduction-tree planner (`aggregate/planner.py`) | implemented and tested |
| Aggregate source validation (`aggregate/validate.py`) | implemented and tested |
| Coverage (`aggregate/coverage.py`) | implemented and tested |
| Query resolution, input-set resolution, aggregate caching | not built |
| Model registry and router (`llm/registry.py`, `llm/router.py`) | implemented and tested |
| Anthropic adapter (`llm/anthropic_provider.py`) | implemented; tests cover construction only, not request shaping |
| Chat-completions adapter (`llm/openai_compatible_provider.py`) | implemented and tested against a mocked client |
| Prompt versioning (`prompts.py`, `prompts/*/v1.md`) | implemented and tested |
| Job queue and worker | table exists in the schema; no worker code |
| API, UI, authentication, audit-log writes | not built |
| Flags workflow | tables exist; no code |
| Golden set, regression runner | not built |
| CLI | `db migrate`, `models list`, `models route`, `prompts list` only |

Where this document describes something not yet built, it says so. "Proposed" means the
design is settled enough to build against; it does not mean it exists.

## 2. Overview

`[D]` marks a deterministic step, `[M]` a model call.

```
  GitHub (App / PAT)
        │
        ▼
  [D] snapshot tables, append-only        pull_requests, pr_files, pr_commits,
        │                                 pr_reviews, pr_comments
        ▼
  [D] diff policy + computed facts        included / excluded with reasons; counts
        │
        ▼
  [D] prompt context                      facts, manifest, description, patches,
        │                                 comments as opaque per-call tokens
        ▼
  [M] pr_summary stage                    typed claims, each with evidence pointers
        │
        ▼
  [D] structural validation               paths, hunk headers, quoted spans, tokens
        │                                     └─ fail ─▶ [M] repair retry ─▶ needs_review
        ▼
      stored claims ─────────────────────▶ [M] verify stage ──▶ verdict + rationale
        │
        │   query {subjects, window, altitude, lens}
        │        │
        ▼        ▼
  [D] input-set resolution ──▶ [D] reduction-tree planning
                                        │
                                        ▼
                               [M] aggregate stage             claims citing source tokens
                                        │
                                        ▼
                               [D] source validation + coverage
                                        │
                                        ▼
                                 API / UI ──▶ reader ──▶ flags ──▶ regression set
                                                                        │
                                                                        ▼
                                                            prompt / model evaluation
```

Three model stages; everything else is deterministic.

| Stage | Input | Output | When it runs |
|---|---|---|---|
| `pr_summary` | one PR: computed facts, input manifest, description, filtered diff, commits, reviews, comments | `PrSummaryOutput`: headline, typed claims each with evidence, description/diff discrepancies, uncertainties, narrative | once per merged PR, cached until prompt, schema or model changes |
| `aggregate` | N atomic summaries or N child aggregates, plus the query | `AggregateOutput`: headline, claims citing source tokens, narrative | on demand per query; cached by input-set hash |
| `verify` | one claim plus the material it cites | verdict (supported / partially_supported / unsupported / cannot_determine) with a rationale | proposed: per atomic claim, default on; on demand for aggregates |

## 3. Ingestion and snapshots

**Source of truth.** Every pull request is fetched and written to append-only tables —
`pull_requests`, `pr_files` (with patch text), `pr_commits`, `pr_reviews`, `pr_comments` —
and summaries are computed from that stored snapshot rather than from the live API. Two
consequences follow. A summary is reproducible, because the exact material a model read
can be recovered. And evidence pointers stay valid regardless of what happens to the
repository afterwards: force-pushed branches, deleted repositories, edited comments.

Re-fetching writes a new row with an incremented `snapshot_version` rather than updating
in place; `is_latest_snapshot` marks the current one. Summaries reference the snapshot
version they read.

**Identity.** A GitHub App installed on the organization is the supported path:
fine-grained permissions (`pull_requests:read`, `contents:read`, `members:read`),
installation tokens that expire in an hour, an audit trail on GitHub's side, no
dependence on a person's account, and compatibility with GitHub Enterprise Server via a
base-URL setting. A personal access token is supported for single-user evaluation and is
labelled as such. `repositories.installation_id` is null for PAT-sourced repositories.
See [ADR-0006](adr/0006-github-app-ingestion.md).

**Mechanism.** Polling with per-repository cursors (`sync_cursors`) is the baseline,
because it requires no inbound network path and works in restricted deployments. Webhooks
(`pull_request.closed` with `merged=true`) are a freshness optimization layered on later;
reconciliation by polling continues regardless, so a missed webhook delays a summary
rather than losing it.

**What is ingested and what is summarized.** All pull requests — open, closed unmerged,
merged — are recorded, so counts are honest and in-flight work is at least visible as
facts. Only merged pull requests are summarized in v1. A merged PR is a completed event
that does not change afterwards, which is what makes a summary computed once and cached
correct rather than merely convenient; an open PR keeps changing and would need its own
invalidation rule. Merge time, not creation time, places a PR in a query window. See
[ADR-0003](adr/0003-merged-pr-atomic-unit.md) and open question 1.

Direct pushes to a default branch that bypass pull requests are invisible to this design.
Reporting them as a per-repository fact is on the roadmap and is not implemented.

**Status.** `ingest/github/client.py` defines the interface the pipeline needs —
`list_merged_pull_numbers` and `fetch_pull_request` — as a `Protocol`, so the pipeline can
be tested against recorded snapshots. No REST or GraphQL implementation exists, and
neither does the write path into the snapshot tables.

## 4. Diff policy

The design principle is that a pull request is read whole. The failure mode of that
principle is a 40,000-line lockfile consuming the context window, so exclusions are
necessary — and the risk exclusions introduce is that the model is shown a partial change
without knowing it.

`ingest/diff_policy.py` (implemented, tested) classifies each file deterministically as
included or excluded with one of seven reasons:

| Reason | Rule |
|---|---|
| `binary` | the file is marked binary |
| `no_patch` | GitHub returned no patch text |
| `lockfile` | filename matches a known lockfile (16 names: `package-lock.json`, `uv.lock`, `Cargo.lock`, `go.sum`, …) |
| `vendored` | path contains `vendor`, `node_modules`, `third_party`, `thirdparty` |
| `minified` | `.min.js` / `.min.css` / `.bundle.js`, or any line longer than 5,000 characters |
| `generated` | path contains `__snapshots__`, `dist`, `build`, `.generated`, or the name matches a generated-file glob (`*.pb.go`, `*_pb2.py`, `*.snap`, `*.svg`, `*.ipynb`, …) |
| `oversize` | patch exceeds 200,000 bytes, or the file was dropped to bring the total under 2,500,000 bytes |

Per-file classification runs first; then, if the included total exceeds the cap, the
largest included files are excluded as `oversize`, largest first, until it fits. Output
order matches input order so the manifest is stable.

The rules are deliberately conservative. Excluding a file the model should have read is
an accuracy bug; including a large generated file is a cost problem. The policy prefers
the cost problem.

Two properties keep exclusions from becoming invisible missing context. Excluded files
still contribute to the computed facts — file counts, additions and deletions are counted
over all files. And the exclusion list is part of the `InputManifest`, which is stored
with the summary, rendered into the prompt, and intended for display next to the summary:
"this summary did not read 3 generated files (12,400 lines)". The model is told what it
is not being shown, and the prompt instructs it not to describe the content of excluded
files while permitting it to note that they changed.

## 5. Deterministic facts

`summarize/facts.py` (implemented, tested) computes `PrFacts` from the snapshot and the
policy outcome: files changed, additions, deletions, included and excluded file counts,
language histogram over included files, test files touched, commit count, reviewers with
their final review state and review count, changes-requested rounds, review and
conversation comment counts, time to merge in hours, labels, linked issue numbers, draft
status, base ref.

These are given to the model as authoritative context and stored separately in
`pr_summaries.facts`. The reason for computing them in code is not that models are bad at
arithmetic in general; it is that a number in a summary is exactly the kind of statement a
reader will quote onward without checking, and the cost of getting one wrong is out of
proportion to the effort of computing it deterministically. The UI renders facts from
data, so a summary cannot misquote a number even if the model repeats one incorrectly in
prose.

Facts are also what remains available for the work the pipeline does not summarize: open
and abandoned pull requests are recorded and counted even though no summary is produced
for them, which is the only current answer to "what is X working on right now".

## 6. Atomic summaries

The `pr_summary` stage output (`schemas/pr_summary.py`, implemented) is a typed structure,
not prose:

- `headline` — one sentence.
- `claims[]` — each an atomic, checkable statement with a `kind` (feature, bugfix,
  refactor, infra, test, docs, perf, security, dependency, chore, other) and at least one
  piece of evidence. The minimum is enforced by the schema; a claim without evidence
  cannot be represented.
- `description_vs_diff[]` — pairs of (what the description says, what the diff shows)
  where they disagree. PR descriptions are a significant source of drift in human status
  reporting, and a summarizer that trusts them uncritically inherits that drift. The
  prompt asks the model to report the discrepancy rather than resolve it in either
  direction.
- `uncertainties[]` — what the model could not determine from the material.
- `narrative` — a short paragraph composed only from the claims above.

Evidence (`Evidence`) is one of six pointer types, with the required fields enforced by a
model validator:

| Type | Required fields | Validated against |
|---|---|---|
| `file` | `path` | the included set of `pr_files` |
| `hunk` | `path`, `hunk_header` | the `@@ … @@` lines of that file's patch |
| `description` | `quote` | the PR body |
| `title` | `quote` | the PR title |
| `review_comment` | `comment_id` | the per-call comment tokens |
| `commit` | `commit_sha` | `pr_commits` sha prefixes |

**Opaque tokens.** The model neither sees nor emits database identifiers.
`summarize/context.py` assigns per-call tokens (`c1`, `c2`, …) to comments in creation
order and hands the model those; the system maps them back and rejects anything
unrecognized. Files are referred to by path and commits by sha, both checkable against the
snapshot. The point is to remove the possibility of a plausible-looking identifier that
refers to nothing — the model cannot guess a token it was not given.

The user turn is rendered deterministically in a fixed order: computed facts, input
manifest, PR title and verbatim description, patches of included files, then commits,
reviews and comments. The order matches `prompts/pr_summary/v1.md` so the prompt and the
material stay aligned.

## 7. Structural validation

`summarize/validate.py` (implemented, tested) runs after generation and before storage. It
is entirely deterministic, which is the reason to keep it separate from verification: it
catches a specific failure class completely rather than probabilistically.

Checks, per evidence pointer:

- **File and hunk.** The path is in the included set. The error message distinguishes a
  path that was excluded by the diff policy from one that is not in the PR at all —
  different errors calling for different responses. For hunks, the header must appear
  verbatim among the patch's `@@` lines.
- **Description and title.** The quote must be a substring after whitespace
  normalization and case folding, so a model that reflows a quoted span is not penalized
  for whitespace while a fabricated quote still fails.
- **Review comment.** The token must be one issued for this call.
- **Commit.** Some commit in the snapshot must start with the given sha prefix.

Schema validity itself is enforced earlier, by pydantic, at the provider boundary.

Language linting is separate and produces warnings rather than errors. A word list of
evaluative terms (`impressive`, `sloppy`, `productive`, `struggled`, …) is matched against
claim text, narrative and headline. The result does not block storage, because some of
these words are legitimate in technical context — a "fast path" is a real thing — and a
lint that rejects output would either be too permissive to matter or would suppress valid
claims. The signal is surfaced for human review instead.

**Proposed, not implemented:** the repair loop. A summary with validation errors is
retried once with the errors appended to the prompt; if it fails again it is stored with
status `needs_review` and is not published. The status values exist in the schema
(`published`, `needs_review`, `rejected`); the orchestration that produces them does not.

## 8. Semantic verification

Structural validation establishes that a pointer refers to something real. It says
nothing about whether that something supports the claim. A model can cite the correct
file and hunk and still misread it — the standing example in `prompts/verify/v1.md` is a
claim that a function "was made thread-safe" supported by a diff that adds a lock, which
holds only if that lock is what makes the shown code thread-safe.

The verification stage is a second model, given the claim, the evidence it cites, and the
surrounding PR material, asked for one of four verdicts and a rationale naming the
evidence that decided it:

- `supported` — the cited evidence establishes the claim as stated.
- `partially_supported` — part of the claim holds, or the claim overstates scope,
  certainty or effect relative to the evidence.
- `unsupported` — the evidence does not establish the claim, or contradicts it.
- `cannot_determine` — the material is insufficient (the claim may depend on excluded
  files, or on code not in the diff).

The verifier is asked to judge, not to rewrite. Its verdict is stored alongside the claim
in `verifications` rather than replacing it, so the disagreement is visible and both
outputs remain available for evaluation.

**Producer independence** is a registry setting on the stage, enforced by the router
(implemented): `model` skips the model that produced the claim, `provider` skips every
model from the producer's provider. Cross-vendor verification — Claude produces, a
self-hosted Qwen checks — is the strongest independence the configuration can express;
`config/examples/mixed.yaml` is that layout.

Limitations worth stating plainly. Two models trained on similar data can share a
misreading, and producer independence reduces but does not eliminate correlated error.
The verifier sees the claim's cited evidence and surrounding material, so it is better
placed to catch overstatement than omission. And verification roughly doubles per-PR cost.
Default-on is proposed on the grounds that this is the cheapest strong signal available
for the property the system exists to provide; open question 5 asks whether that is the
right default.

**Status:** the schema (`schemas/verify.py`) and the prompt exist. `verify/` contains no
implementation.

## 9. Query model

A query is `{subjects, window, altitude, lens}`.

**Subjects** are people, teams or repositories. Team membership is temporal
(`team_memberships.valid_from` / `valid_to`, indexed for both directions) and is resolved
as of each pull request's merge date. Without this, "the platform team's Q2" would
silently include work someone did on a different team before transferring in, and exclude
work done by someone who has since left — a failure that produces a plausible-looking,
quietly wrong answer.

**Window** is any half-open `[start, end)` interval. Nothing is pinned to weeks,
sprints or quarters. The half-open form means adjacent windows partition merges without
overlap or gaps.

**Altitude** is one of `ic`, `lead`, `manager`, `director`, `exec` (`schemas/aggregate.py`,
implemented). It selects the prompt variant, the target length, and the expectation of how
many source claims a single aggregate claim should rest on: at `ic`, claims rest on one or
a few sources; at `exec`, each should rest on a large share of the sources or be
explicitly marked as a small but material item. Altitude does not change the provenance
rules — a director-level claim cites its sources exactly as an IC-level claim does.

**Lens** — themes such as reliability or security, mapping to claim kinds — is proposed
and not implemented. It appears in the stored `query` JSON and in the cache key so that
adding it later does not invalidate existing entries, but there is no lens type in the
code.

**Status:** query resolution is not built. The `aggregate_summaries` table stores the
query, altitude and window, and the schemas exist; nothing resolves a query into an input
set yet.

## 10. Query-time aggregation

Higher-level views are generated when asked, from the atomic summaries whose PRs merged
in the window and match the subjects. The input set is recorded in `aggregate_inputs`, so
coverage is a join rather than an estimate.

The decision not to precompute rollups ([ADR-0008](adr/0008-query-time-aggregation.md)) is
worth stating with its cost. Fixed calendar rollups (week → month → quarter) are cheaper
and give predictable latency. They impose a granularity the reader did not ask for: a
question about the two weeks around a launch cannot be answered from weekly rollups that
straddle it. And unless each level of the rollup chain is itself stored with full
provenance, the connection from a quarter's sentence to the pull requests behind it is
lost — at which point the design is this one, with worse cache keys and stale results.

The cost paid instead is latency for large windows and higher per-query model spend,
mitigated by caching (§13) and by running each level of the reduction tree in parallel.
A query over a year of a large team's work will take long enough that the UI needs to
show progress rather than a spinner.

### Reduction tree

A large team over a long window produces more atomic summaries than fit in any model's
context. `aggregate/planner.py` (implemented, tested) builds a tree of calls.

This is a query execution strategy, not a scheduled rollup hierarchy. The distinction is
that the tree's shape is derived from the input set of one query and the routed model's
budget; it is not a fixed organizational or calendar structure, and it is recomputed when
either input changes.

Mechanics:

1. Inputs are ordered deterministically. Each `PlanItem` carries an `order_key` (merge
   time, then subject, then id) and a token estimate, and items are sorted by that key.
   Determinism is what makes the tree — and therefore the cache keys and the stored
   intermediate aggregates — reproducible for the same query.
2. Items are packed greedily into groups that fit `budget_tokens`, with a small per-item
   overhead allowance (default 50 tokens) for the framing the prompt adds around each.
   Ordering is preserved, so groups are contiguous in merge-time order and a child
   aggregate covers a coherent sub-period.
3. If one group results, that is a single call and the tree is one node.
4. Otherwise each group becomes a leaf node producing a child aggregate. Those children
   are then treated as items of an estimated size (default 4,000 tokens each, the planning
   estimate for a child summary as an input to its parent) and packed the same way,
   recursing until one node remains.

Three conditions raise `PlanningError` rather than producing a degraded plan: an empty
input set, a single item larger than the budget, and a budget too small to fit two child
summaries — the last because a tree that cannot reduce by at least a factor of two would
not terminate.

Each child is a stored aggregate with its own claims, sources and coverage, linked to its
parent by `aggregate_summaries.parent_id`. Drill-down therefore works at every level:
parent claim → child claim → PR claim → file or hunk.

## 11. Aggregate provenance

The model emits `sources: [token, …]` for each aggregate claim, where the tokens are the
same kind of opaque per-call identifiers used for comments in the atomic stage. The system
maps tokens back to `pr_claims.id` or to a child `aggregate_claims.id`.

`aggregate/validate.py` (implemented, tested) enforces this before storage, with a
deliberate asymmetry:

- A claim citing no valid source is dropped entirely, and the drop is recorded on the
  aggregate.
- A claim citing some valid sources keeps them; unknown tokens are trimmed and counted,
  and the surviving list is deduplicated with order preserved.
- If every claim is dropped, the aggregate fails rather than being stored empty.

Trimming rather than dropping in the partial case is a judgment call: a claim resting on
four real sources and one hallucinated token is more likely to be a citation error than a
fabricated claim, and dropping it would silently reduce coverage. The count of trimmed
sources is retained so the tradeoff can be evaluated against real output rather than
argued about.

In the database ([ADR-0004](adr/0004-provenance-as-rows.md)), each row in
`aggregate_claim_sources` has two nullable foreign keys — `pr_claim_id` and
`source_aggregate_claim_id` — with `CHECK (num_nonnulls(...) = 1)`. Exactly one is set,
and both are real foreign keys, so the database enforces that a cited claim exists. A
generic `(from_type, from_id, to_type, to_id)` reference table would be more compact and
would give up precisely that guarantee.

Drill-down is a recursive query over `aggregate_claim_sources` down to `pr_claims`, then a
join to `pr_claim_evidence`, then to `pr_files`, `pr_comments` or `pr_commits`. The
indexes on both source columns exist for this traversal in both directions: from a
high-level claim down to evidence, and from a pull request up to every view that mentioned
it.

## 12. Coverage

Coverage answers a question provenance cannot: of the work eligible for this view, how
much contributed to it?

`aggregate/coverage.py` (implemented, tested) takes the input id set, the validated
claims, and a map from each citable source token to the input it belongs to. It returns
`input_count`, `cited_count`, the sorted `cited` and `uncited` id lists, and the ratio. An
input counts as cited if at least one surviving claim cites at least one of its claims.

The `uncited` list is the output that matters, and it is the reason the input set is
stored rather than recomputed: an uncited id is only meaningful against a denominator that
was fixed at the time the view was produced. The proposed rendering (no UI exists) shows
the uncited inputs next to the narrative with each one's headline and size, so the
omission is as visible as the claims. `Coverage.is_low()` compares the ratio against a
threshold (default 0.6, also exposed as `ALTISCOPE_LOW_COVERAGE_THRESHOLD`); the schema
has a `low_coverage` status on `aggregate_summaries` for aggregates that fall below it.

Coverage is computed at every level of the reduction tree, which matters: a parent claim
that cites a child faithfully still inherits whatever the child omitted, so a leaf with
poor coverage needs to be visible even when the parent looks complete.

What coverage does not do is worth being precise about. It measures the fraction of
*eligible inputs* cited, not the fraction of *real work* represented — pull requests that
were never ingested, and engineering work that never became a pull request, are outside
the denominator entirely. It also treats a one-line dependency bump and a two-month
migration as one input each. Whether the ratio should be weighted, and by what, is an open
question (§22).

## 13. Caching and invalidation

**Atomic summaries.** `pr_summaries` is unique on
`(pull_request_id, prompt_version_id, schema_version, model_id)`. Changing the prompt, the
schema or the model produces a new row rather than overwriting; the previous row is kept
with `is_current = false`, and a partial unique index
(`pr_summaries_current_idx ... WHERE is_current`) enforces at most one current summary per
pull request. Keeping superseded summaries is what makes it possible to compare two models
or two prompt versions on the same PR without re-running the old one.

**Aggregates.** Cached by a hash over the sorted input `pr_summary` ids, altitude, lens,
prompt version and model, stored as `aggregate_summaries.input_hash` and indexed together
with the prompt version, schema version and model id. Because the identity is the input
*set* rather than the query text, two differently phrased queries that resolve to the same
summaries at the same altitude hit the same cache entry, and a query whose window has
acquired one new merged PR does not.

This is a cache of an on-demand result. Nothing is computed before it is asked for, and a
cache hit is the same answer to the same question rather than a stale rollup.

## 14. Model registry and routing

Altiscope is designed to run against any model an operator can reach: hosted APIs, cloud
provider endpoints, or open-weight models on their own hardware. This is a requirement
rather than a preference, because enterprises frequently mandate a provider and some
forbid any model outside their network. Handling it in configuration keeps that constraint
from reaching the pipeline.

`config/models.yaml` (loaded and validated by `llm/registry.py`, implemented and tested)
has three parts.

**Providers are endpoints, not vendors.** A provider entry has a `kind` (the adapter), an
optional base URL and the name of the environment variable holding its key. The same kind
can be declared any number of times for different endpoints — a local Ollama and a shared
vLLM cluster are two providers of the same kind. Two adapter kinds are implemented:

- `anthropic` (`llm/anthropic_provider.py`) — native structured output via
  `messages.parse(..., output_format=...)`, adaptive thinking, effort levels via
  `output_config`, prompt caching on the system block (stable per prompt version), exact
  token counting through the count-tokens endpoint, and `stop_reason == "refusal"` mapped
  to a refusal category.
- `openai_compatible` (`llm/openai_compatible_provider.py`) — anything speaking the
  chat-completions protocol: OpenAI, Azure OpenAI, Ollama, vLLM, llama.cpp, LM Studio,
  and hosted gateways.

Claude on Bedrock, Vertex and Foundry is the same `anthropic` adapter with a different
client class; those clients are not wired in (roadmap item 6). A Gemini adapter is
proposed as a third adapter of the same shape and does not exist.

**Models declare capabilities.** `json_schema` (server-enforced schema), `json_mode`
(valid JSON, schema prompted), `reasoning_effort`, `token_counting`. The chat-completions
adapter selects the strongest structured-output mode the model declares and falls back
through `native → json_mode → prompt`, stripping code fences in the weakest mode. The mode
used is recorded on the call. Output that fails to parse is returned with
`stop_reason="invalid_output"` and the validation error attached — it is never raised as
an exception, because an unparseable response is an expected outcome for a weak model and
the pipeline's repair retry is the right handler for it.

The reason capability fallback is safe is that the pipeline's own validation against the
snapshot (§7) is what establishes correctness, not the provider's schema enforcement. A
model without native schema support converges more slowly; it is not less checked.

**Stages route by fit and preference.** Each stage declares an ordered candidate list, an
effort level, reserved output tokens, and (for verification) a producer-independence rule.
`llm/router.py` walks the candidates in order, skipping any blocked by producer
independence and any whose input budget is smaller than the estimated input, and returns
the first that fits along with a `rule` (`default`, `escalated_for_size`,
`independent_of_producer`) and a plain-language `reason` naming what was skipped and why.
If nothing fits, `RoutingError` names every candidate and its budget, and the caller's
correct response is to reduce the input — which is what the reduction-tree planner does.

The input budget is
`floor(context_window × input_budget_fraction) − reserved_output_tokens`, with the
fraction defaulting to 0.75. The remainder is headroom for the system prompt, the schema
and the output. The registry rejects at load time a stage that reserves more output tokens
than a candidate model allows, along with unknown provider references, unknown candidate
models, and missing stages — configuration errors surface at startup rather than mid-run.

Routing is by fit and preference only. There is no cost-based logic: the registry records
per-model cost so it can be reported, deliberately not so the router can trade quality for
it silently.

**Token counting** goes through the provider protocol. The Anthropic adapter uses the
exact endpoint when the model declares `token_counting`. The chat-completions protocol has
no portable equivalent and a tokenizer for one model is wrong for another, so that adapter
returns a character-based estimate (3 characters per token, rounded up) that deliberately
overestimates. Planning errs toward smaller inputs.

**Provenance of the call itself.** Every call writes an `llm_calls` row: stage, provider,
model id, prompt version, schema version, effort, routing rule, routing reason, the
candidate list considered, estimated and actual token counts, cache read and write tokens,
cost, latency, provider request id, stop reason, status, and the request hash. Every
summary, aggregate and verification references the call that produced it. This is what
makes empirical model comparison possible: which model produced this, why was it chosen,
and how did its output fare.

Routability and suitability are separate questions. Smaller open-weight models produce
more invalid evidence pointers and more subtle misreadings that pointer validation cannot
catch, so the registry's willingness to route to a model says nothing about whether it
should be a stage default. That question is settled by results on the golden set, which
does not exist yet — the current defaults in `config/models.yaml` are a starting
configuration, not a finding. See [ADR-0005](adr/0005-model-registry-routing.md).

## 15. Storage

Postgres only ([ADR-0002](adr/0002-postgres-only.md)). Migrations are plain SQL files in
`migrations/`, applied in order by a small runner, each in one transaction. Never edit an
applied migration; add a numbered one.

The relational model is doing real work here, which is why the choice is not incidental.
Provenance is a graph traversed in both directions, and the constraints that make it
trustworthy are ones the database can enforce:

- `pr_claim_evidence` has nullable foreign keys to `pr_files`, `pr_comments` and
  `pr_commits` plus a `CHECK` selecting exactly the right shape per `evidence_type`, and a
  second `CHECK` requiring a `hunk_header` for hunk evidence. An evidence row cannot point
  at a file that does not exist, and cannot be the wrong shape for its type.
- `aggregate_claim_sources` has the two-way `CHECK (num_nonnulls(...) = 1)` described in
  §11, with uniqueness on each (claim, source) pair so a claim cannot cite the same source
  twice.
- `verifications` and `flags` use the same pattern to attach to exactly one target — a PR
  claim, an aggregate claim, or (for flags) a whole summary or aggregate.
- `aggregate_inputs` records the full input set of a leaf aggregate as a join table, which
  is what makes coverage a query.
- `pull_requests` has `CHECK (state <> 'merged' OR merged_at IS NOT NULL)`; `pr_files` has
  `CHECK (included = (exclusion_reason IS NULL))`, so a file cannot be both included and
  excluded-for-a-reason.

Supporting SQLite alongside would mean either a lowest-common-denominator schema — losing
JSONB operators and `SKIP LOCKED` — or verifying every provenance query against two
dialects. Hand-written SQL rather than ORM-generated migrations is a legibility choice:
the schema is the provenance contract and is meant to be read as SQL by someone deciding
whether to trust the system.

`llm_calls` stores full request and response payloads by default, which contain diffs and
therefore duplicate source code in the database. `request_hash` is always stored;
`request_payload` and `response_text` are nullable, so a `hashes_only` retention mode
(`ALTISCOPE_LLM_PAYLOAD_RETENTION`) trades reproducibility for storage. See open question
3.

`migrations/0001_initial.sql` is the current data model in full. An integration test
applies it to a real Postgres in CI and asserts that the provenance `CHECK` constraints
actually reject malformed rows, on the principle that a constraint nobody has tried to
violate is a comment.

## 16. Background jobs

Ingestion, summarization, verification and aggregation run as background work through a
Postgres job table: `jobs` with `kind`, `payload`, status, attempt counter, `max_attempts`,
`run_after` for backoff, `locked_at`, and a partial index on ready rows. Workers claim work
with `SELECT ... FOR UPDATE SKIP LOCKED`, which gives concurrent workers without a
coordination service.

The justification is throughput: pull requests merge at human pace, so a large
organization generates thousands of jobs a day, not thousands a second. A dedicated queue
would add an operational dependency to every deployment in exchange for headroom this
workload does not need. If that assumption turns out to be wrong — a large backfill is the
likely case — the queue is behind a small interface and the table is not the hard part to
replace.

**Status:** the table exists; there is no worker.

## 17. Deployment

One container image, two roles, plus Postgres:

- `altiscope serve` — JSON API and UI.
- `altiscope worker` — the job queue consumer.

Neither command exists yet; the CLI currently provides `db migrate`, `models list`,
`models route` and `prompts list`.

Outbound network access is limited to GitHub (or GHES) and the configured model endpoints.
Nothing else leaves the deployment. Because a provider is an endpoint, an organization
that requires models to stay inside its network configures a local or internal endpoint
and changes nothing else; `config/examples/ollama.yaml` is a fully local layout.

## 18. Authentication and authorization

**Status:** proposed; not implemented.

OIDC for organizations with SSO, GitHub OAuth for small ones. The authorization baseline
mirrors GitHub: a person can read a summary if they can read the repository it came from.
Roles above that — org admin, team lead views — are additive rather than replacing the
baseline.

Aggregates complicate this, because an aggregate can draw on repositories the reader
cannot all see. The intended resolution is that the permission check happens at input-set
resolution, so a reader gets an aggregate over the subset they may see, with coverage
computed over that same subset — an aggregate should not become a channel for reading
summaries of repositories the reader has no access to, and coverage should not report a
denominator the reader cannot inspect.

The check belongs in a single function at the API boundary from the first commit that
serves a request, because a permission check added later is a permission check that was
missing somewhere in between. `audit_log` records who viewed what and who flagged what.

## 19. Human feedback and evaluation

**Status:** the tables exist; the workflow does not.

**Flags** are first-class rows on any claim, summary or aggregate, raised by a person,
with a category naming the failure mode: `factual_error`, `overstated`, `understated`,
`omission`, `misattribution`, `selective_emphasis`, `other`, plus free text and a
resolution status. The categories are chosen to match the failure modes in §21 rather than
to be a generic feedback form — an omission and an overstatement call for different
responses, and a single "this is wrong" button loses that.

Flags are visible on the claim wherever it is rendered, and propagate upward: an aggregate
claim whose sources carry open flags is marked, so a correction at the atomic level
reaches the views built on it rather than staying where it was filed.

**Evaluation.** Flagged and human-corrected claims accumulate into a regression set. A
prompt or model change is measured against it before becoming a default, comparing
claim-level agreement with the human corrections. Prompts are versioned files
(`prompts/<stage>/vN.md`) with front matter and a sha256 recorded on every call; editing a
file that has produced published summaries would make those rows unreproducible, so
changes are new version files.

The evaluation loop is the mechanism that turns "which model should this stage use" from
an argument into a measurement, and it is the most important thing that does not exist
yet. Until it does, every quality claim about this system is a hypothesis.

## 20. The personnel boundary

Summaries describe engineering work. The system is not designed to evaluate employees, and
this is enforced in several places rather than stated once:

- Prompts at every stage instruct the model to describe work and not characterize people,
  and forbid words evaluating effort, pace or quality.
- The validator lints for evaluative language and surfaces it for human review.
- `misattribution` and `selective_emphasis` are flag categories, so the failure has a name
  and a reporting path.
- Cross-developer comparison views, if built, render each person's own aggregate and facts
  side by side. The model is not asked to compare people, because that is the surface where
  a summary most easily becomes a performance verdict.

[`THESIS.md`](../THESIS.md) §7 gives the evidentiary argument: pull request activity omits
design work, mentoring, review given to others, incident response and the work of not
building something, and is systematically biased toward contributions that are legible in
a diff. See [ADR-0007](adr/0007-accuracy-over-breadth.md) and open question 2.

## 21. Failure modes and the mechanisms that address them

Most of the architecture is easier to evaluate as a set of responses to specific failures.
None of these mechanisms eliminates its failure; each detects it, reduces its likelihood,
or makes it measurable.

| Failure | Mechanism | What it actually achieves |
|---|---|---|
| Model invents an evidence pointer | Structural validation against the snapshot; opaque per-call tokens instead of ids | Eliminates this class for pointers the system can check. A path, quote, comment token or sha that does not exist is rejected before storage. The model cannot guess a token it was not issued. |
| Model cites real code but misreads it | Semantic verification by an independent model | Detects some of it. Probabilistic, and correlated failure between models remains possible; the verdict is recorded, not enforced. |
| Summary is accurate but selectively incomplete | Coverage over a recorded input set; `low_coverage` status; uncited list shown to the reader | Makes omission visible and measurable over eligible inputs. Does not detect work that never became an ingested pull request. |
| Producer and verifier share the same blind spot | `producer_independence` (`model` or `provider`); cross-vendor configuration; golden-set evaluation | Reduces correlation and makes it configurable. Does not establish independence — the evaluation set is what would measure it. |
| Query exceeds the model's context | Deterministic reduction tree with stored intermediates | Keeps the query answerable and provenance traversable at every level. Adds latency and one more layer of synthesis loss. |
| Source material changes after summarization | Versioned append-only snapshots; summaries reference the version they read | Makes summaries reproducible and evidence pointers durable. Costs storage, including diffs stored twice when payloads are retained. |
| Large generated files crowd out the real change | Deterministic diff policy with reasons, disclosed in the input manifest | Keeps the input tractable and the exclusions visible to both model and reader. A wrongly excluded file is still a wrongly excluded file; the rules are conservative for that reason. |
| Team composition changes over the window | Temporal `team_memberships` resolved at each PR's merge date | Prevents attributing work to a team the author was not on at the time. Depends on membership history being accurate, which for imported data it may not be. |
| Model misstates a number | Facts computed in code, stored separately, rendered from data | Removes numbers from the model's responsibility in the rendered output. The model can still misstate one in narrative prose; the lint and flags are the fallback. |
| Description and diff disagree | `description_vs_diff` reported rather than resolved | Surfaces the discrepancy to the reader instead of silently trusting one side. |
| New prompt or model regresses quality | Versioned prompts hashed on every call; superseded summaries retained; regression set | Makes regression measurable and old output comparable — once the golden set and regression runner exist. Currently the weakest link. |
| Summary becomes a performance judgment | Prompt constraints, language lint, side-by-side comparison views, flag categories | Reduces the likelihood and names the failure. It is a product boundary, not a technical guarantee. |

## 22. Open questions

These change what gets built and are not settled.

1. **Open and abandoned pull requests.** Merged-only summarization makes in-flight work
   invisible: a manager asking "what is X working on" sees counts, not content. The
   proposal is to ingest everything, summarize merged only, and expose open and abandoned
   work as facts (counts, ages, titles). Summarizing open PRs is feasible but breaks the
   one-time-event property that makes caching correct, and needs its own invalidation rule.
2. **Cross-developer comparison.** The recommendation is side-by-side rendering from each
   person's own aggregate, never a model-authored comparative judgment (§20). This
   constrains a view some readers will ask for, and the constraint should be confirmed or
   overruled deliberately.
3. **Payload retention.** Storing full prompts means storing source code twice. Default is
   full retention for reproducibility, with a hashes-only mode. Which should be the
   default for an enterprise deployment is unresolved.
4. **User interface.** The proposal is server-rendered HTML with HTMX for v1, keeping the
   repository in one language while the hard problems are unsolved, with the JSON API as
   the contract a richer front end could consume later. This is the most reversible
   decision here.
5. **Verification default.** Default-on verification roughly doubles per-PR cost. Whether
   that is right may depend on the producing model, and the answer should come from the
   evaluation set rather than from this document.
6. **Coverage interpretation.** The 0.6 threshold is a guess. Unweighted coverage treats a
   one-line dependency bump and a two-month migration as equal inputs; weighting by size
   would distort differently. Whether the threshold should vary by altitude — an exec
   summary legitimately cites fewer sources directly — is unresolved, and so is whether
   `low_coverage` should block publication or only annotate it.

## 23. Deliberately out of scope

- **Retrieval or embedding search over pull request content.** A pull request is bounded
  and is read whole. Retrieval would reintroduce selective omission at the level where it
  is hardest to detect: whatever the retriever does not return is silently absent, and
  coverage cannot measure it.
- **Commit-level summaries.** Commits are noisy — work-in-progress, fixups, rebase
  rewrites — and rarely carry a coherent rationale.
- **Scheduled rollups.** §10.
- **Employee performance ranking or evaluation.** §20.
- **Code quality, security and compliance analysis.** No such stage exists. The claim and
  evidence shape was chosen so that a future finding — a statement about a change, with
  validated evidence, that can be verified and disputed — would be the same kind of row as
  a claim rather than a new subsystem. That is an argument about the data model, not a
  claim that such analysis is planned or that the shape will prove adequate.
