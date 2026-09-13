# ADR-0012: Pin recipes and sources, and preserve comparison results

Status: Proposed (2026-09-13; owner acceptance pending).

Issue: [#41](https://github.com/shashvatsinha/altiscope/issues/41), within
[M3](https://github.com/shashvatsinha/altiscope/issues/6).
Extends [ADR-0010](0010-pr-review-provenance.md) and
[ADR-0011](0011-aggregate-report-provenance.md). For pinned comparison and assessment
execution, this proposes replacing ADR-0005's candidate routing and registry-key
independence with the rules below. Production routing remains as implemented.

This is a design contract, not an implemented feature. Following the
[ADR status convention](README.md), acceptance requires an explicit owner decision.
Record its date, decision and durable issue/PR reference here, and update the index,
before treating the new product decisions as accepted. Passing checks or merging a
proposal does not by itself supply owner acceptance.

## Why and recommendation

M3 must compare configurations on the same saved material without replacing useful
production reports. A model name and prompt hash alone cannot execute an old recipe.
A final call ID cannot describe a failed preflight, a repair, or reuse of an output
that someone has already reviewed.

Use immutable recipe versions, frozen sources, immutable terminal results, and
separate invocation membership records. Initially compare aggregates using **one
generation step over identical saved input reports**. Keep whole-result assessment
and human judgment separate from generation success. Do not add per-claim assessment,
model-selected citations, coverage scores, numeric confidence, or employee evaluation.

## Evidence from the current implementation

Inspected main at `f9f066959de75c01bb8ee0c8cc85db791e0bdc6d`, released by
[PR #40](https://github.com/shashvatsinha/altiscope/pull/40):

- `llm/registry.py` resolves model wire names, capabilities, provider configuration,
  prices and budgets. It has no canonical underlying-model identity. `router.py`
  chooses among candidates and excludes producer registry keys/provider names;
  equivalent aliases can therefore evade its model-independence check.
- `prompts.py` hashes the complete source text, including front matter, and derives
  the system body. `store/calls.py::save_calls` saves that text plus actual attempt
  metadata, hashes, selected configuration, usage and estimated cost. It returns
  prompt/call IDs; it does **not** persist parsed application output. Its registry
  argument must not become a route back to mutable configuration for saved recipes.
- `summarize/service.py::prepare` computes facts and a manifest, then
  `summarize/context.py` renders deterministic input. `store/accounts.py` saves
  facts, omissions and narrative, but rejects a zero-attempt result and updates
  production `is_current` on success. It is not a comparison-result writer.
- `aggregate/generate.py` already generates one node with at most one repair.
  `aggregate/service.py` also routes, plans trees and uses production caches;
  comparison execution cannot reuse that orchestration unchanged.
  `store/aggregates.py` checks exact report inputs and saves output and calls together.
- PR output is `PrReviewOutput` schema 3; aggregate output is `AggregateOutput`
  schema 4. `VerificationOutput` schema 1 describes a retired per-claim task.
  Migration 0006 is the latest migration. Existing `verifications`, `flags` and
  aggregate-claim structures are not M3 dependencies.

Paths above are relative to `src/altiscope/`. These findings support reusing the
adapters, validation, source rendering and call writer, with a separate comparison
persistence layer. No application code or migration changes belong in #41.

## Recipe contract

A recipe is a named, immutable version of a resolved generation configuration.
Creating a name saves version 1; another save under that name appends a version,
even if settings repeat. Concurrent saves allocate versions transactionally. Exact
version IDs are execution inputs; `latest` is only a selection convenience resolved
before an invocation is saved. No stored recipe executes by looking up today's
registry key or today's prompt file.

`RecipeVersion` contains an ID, name/version, creation time, configuration-format
version, canonical configuration hash and these resolved values:

| Group | Required stored content |
|---|---|
| Task | One internal stage; output-schema ID/version; prompt-version FK and hash |
| Prompt | Immutable `prompt_versions` row with complete `source_text` including version/stage/schema front matter, derived body, and SHA-256; original path is traceability only |
| Model | Original registry key; configured provider name; wire name; underlying-model identity or explicit unknown; identity evidence and identity-policy version; versioned versus mutable-alias designation |
| Provider | Adapter kind/version, explicit resolved endpoint, timeout, credential reference, effective retry policy, and supported endpoint/routing options that affect execution |
| Capabilities | Declared capabilities, resolved output mode, context window and model output limit |
| Generation | Requested and effective effort, output reservation and wire token parameter; supported sampling/seed options if used; explicit omitted/provider-default markers for unset parameters |
| Budget | Input-budget fraction, derived input limit, token estimator/version, schema/envelope allowance, repair limit and repair-instruction version |
| Output contract | Registered Pydantic contract ID/version, canonical JSON Schema content/hash, validator implementation version |
| Pricing | Currency, input/output rates and units, cache-token treatment, estimator version, provenance/as-of time and whether rates are unavailable, configured estimates or explicitly free |
| Interpretation | Framework build/commit, adapter and relevant dependency versions, prompt-parser version, source-format, renderer, input-policy and facts-computation versions |

Preserve prompt content before the first call, including recipes that never run.
New recipe references require complete source text and matching hashes; do not
invent missing front matter for a historical prompt. Content-addressed rows are
immutable after creation. Store schema content as well as its hash because library
upgrades can change emitted JSON Schema. The registered Pydantic validator remains
necessary: JSON Schema content alone cannot reproduce custom Python validation.

Resolve SDK default endpoints into explicit endpoint values when creating the
recipe. Reject embedded credentials in URLs or configuration. Store environment or
credential-profile references only, never resolved secrets; resolve the reference
at execution. Missing credentials fail explicitly. Record SDK/provider defaults
that cannot be pinned as limitations instead of claiming they are fixed values.

Creation validates nonblank prompt text, all references, supported settings, positive
limits, and `reserved_output_tokens <= max_output_tokens`. Loading reconstructs
execution configuration from the saved values and verifies content hashes and
implementation compatibility. Unknown adapters, validators or preparation versions
fail clearly; no silent reinterpretation by newer code. Historical results remain
readable even when their execution implementation is unavailable.

Keep internal stages `pr_summary`, `aggregate`, `verify`; “PR review” and
“assessment” are descriptive names. Stage, prompt front matter and registered output
schema must agree. #43 initially registers PR schema 3 and aggregate schema 4.
#45 registers a new whole-result assessment contract and a new published prompt
version under `verify`. The retired `VerificationOutput` schema 1 is ineligible;
#43 must not invent a usable placeholder assessment recipe.

An **output schema** is a versioned Pydantic response contract. A **database schema**
is changed by numbered migrations. Their version numbers are independent.

### Output modes and validation

For the existing `openai_compatible` adapter, capabilities select:

- `native`: pass the Pydantic schema to `chat.completions.parse` for the endpoint's
  structured-output facility, with SDK parsing. Support depends on the endpoint.
- `json_mode`: request `response_format={"type": "json_object"}`, put the schema
  in instructions, strip surrounding code fences and validate JSON locally. The
  endpoint requests JSON syntax, not enforcement of the complete response contract.
- `prompt`: put the schema in instructions without requesting a server JSON mode;
  strip surrounding code fences and validate locally.

The existing Anthropic adapter always uses `messages.parse(output_format=Model)`
and reports `native`; it does not implement those two fallback modes. Recipe
validation must reject incompatible mode declarations for that adapter. It sends
adaptive thinking and effort directly. The compatible adapter sends effort only
when supported and maps `xhigh`/`max` to `high`; recipes retain both requested and
effective settings. Provider-specific behavior stays inside adapter modules.

Every usable result passes application validation for its registered contract,
including nonblank required text and acceptable completion status. Refusals,
truncation and transport failures are not usable outputs. Record actual mode on
each call, including failures; never silently fall back to another mode. Validation
checks shape, not factual accuracy. Mode metadata describes experimental conditions;
it cannot establish why one recipe's quality differs from another's.

Pinning does not guarantee byte-identical stochastic outputs, stable remote service
behavior, or an unchanged vendor alias. Save returned model identifiers/request IDs
per call and expose unresolved identity/default/usage limitations in inspection.

## Frozen source contract and aggregate scope

A `ComparisonSource` is immutable and has a kind, source-format version, repository
FK and stable numeric GitHub repository ID, locator at capture, content hash, and
stored preparation content. Locators remain historical display/navigation metadata;
a repository rename does not refresh a frozen source. Content hashes use versioned
canonical serialization, retaining array order. Database FKs establish identity;
hashes detect mismatched content and do not replace those links.

For `pr_summary`, freeze an exact merged `pull_requests` snapshot ID/source hash,
PR number, normalized snapshot version, computed facts, manifest of included and
excluded material, effective policy settings and rule versions, and the exact
prepared source text plus hash. Store facts/renderer versions and ordering rules.
The snapshot and manifest retain what was omitted and why. This is a generation
source, **not an existing generated PR review**. Preparation happens once for all
members. Do not re-run today's diff policy when loading a source.

For `aggregate`, freeze a nonempty ordered list of exact successful `pr_summaries`
or `aggregate_reports` version IDs. Each input retains its saved rendered text/hash,
source hash, kind and ordinal, with relational links to its original report. Also
freeze the query, explicit UTC bounds and boundary semantics (M2 uses inclusive
bounds, with user dates expanded to UTC day start/end), selection rule, altitude (`ic`, `manager`,
`exec`), query instruction and source rendering/version. Validate repository
membership through the exact reports; record any selected subset or additional
window inputs explicitly. Code derives all underlying PR identities and links
from the saved lineage, regardless of which changes the output mentions.

Comparison creation reads only saved sources. Selection may resolve latest reports
once, inside the source-freeze transaction, or accept explicit versions. Missing,
duplicate or failed input reports reject source creation; an empty selection creates
no invocation or calls. Collection or missing-report generation is a separate explicit
preparation action. Comparisons never refresh GitHub, regenerate source reports,
or substitute newer versions. Exact saved input text survives renderer upgrades and
`hashes_only` retention, and the original version graph remains navigable.

Set `experiment_scope=single_step` for aggregate invocations in M3. Every recipe
receives the same complete saved report set, order, query and altitude. Recipes may
vary instructions, model or settings, but cannot prune inputs, rerender source
material with a different policy, or build different intermediate trees. A recipe
requiring a different preparation contract is incompatible with that source.
Assessment and adapter schema instructions are separate from this common source.

If a recipe cannot fit the complete request, save an explicit `oversized_input`
failure with zero attempts; continue siblings that fit. Do not route to another
model or silently reduce the input. #47 must describe this as a comparison of one
composition step conditional on fixed input reports, not end-to-end PR-to-summary
quality, tree-planning quality or full-pipeline cost. Saved intermediate aggregates
may be inputs, but their earlier generation is outside the measured step and their
costs must not be presented as newly incurred comparison cost.

Whole-tree experiments are deferred. Introducing them requires a recorded design
revision before #42/#44/#47 rely on it: a distinct scope/cache namespace, frozen leaf
sources, per-recipe tree/planner metadata, per-node input/result/attempt lineage,
complete cost accounting including failed nodes and repairs, and an evaluation
protocol that does not silently pool the two scopes.

## Invocation, result, reuse and cost

An invocation freezes a source ID, stage/scope, ordered explicit recipe versions,
force-rerun choice, retention policy, protocol version when applicable, and execution
build. It has a separate member for each recipe version (at least two distinct
versions for a comparison). Invocation lifecycle may change from running to a
terminal summary; the frozen specification does not change.

A `ComparisonResult` is the immutable terminal outcome of one recipe on that source.
It retains ID, origin invocation/member, source and recipe IDs, cache key/version,
timestamps, status, sanitized errors, parsed output/schema identity and hash, and
ordered links to every actual generation attempt. Use statuses `succeeded`,
`preflight_failed`, `invalid_output`, `refused`, `failed`; error codes distinguish
budget, compatibility, credentials, truncation and transport outcomes. A failed
result has no usable parsed output. A successful result retains the validated
document independently of raw-response retention.

A later invocation member can reference the same successful result with
`disposition=reused` and its original member/result identity. It creates no result
copy and no calls. A member with `disposition=generated` owns one newly finalized
result, successful or failed. An explicit forced rerun bypasses reuse and produces
a new result ID, even when output bytes happen to match. Reviews always address
result IDs, never a mutable “latest” slot or just a recipe name.

Cache only successful comparison results. Use a versioned `comparison` namespace
over source identity/content/preparation, stage/scope, exact recipe-version ID and
configuration hash, and execution-contract versions. Include query/altitude through
the frozen source. Retention is recorded per origin: reusing a `hashes_only` result
under a full-retention invocation does not manufacture missing raw payloads; request
a forced rerun to obtain them. Choose the latest matching success deterministically
by creation time and ID. Concurrency may create two successes; preserve both.

Comparison lookup never consults production caches or current-report selection.
Comparison writes never insert production reports or update `is_current`. Production
queries never read comparison results. Reading explicit production report versions
as aggregate sources is permitted and does not make their outputs cache candidates.

Each attempted model request, including the one permitted malformed-output repair,
is a real `llm_calls` row linked in order to its result. Preflight failure has zero
rows; a repair blocked by budget retains the original failed call only. No synthetic
call represents reuse, a preflight decision or an assessment that was not requested.
M3 comparison adapters must disable hidden SDK transport retries (zero automatic
retries) so attempt accounting remains observable. A later explicit transport-retry
policy would need its own recorded attempts and bounds; it is not the output repair.
Recorded demo outputs use a labeled fixture origin, not purported live model calls.

Budget each actual request against the declared recipe model: system instructions,
frozen source text, output schema, adapter/envelope overhead, and repair additions,
with output tokens reserved. Preserve the estimator version and estimate. Existing
character estimates are approximate; a provider may still reject a request. Allow
one replacement for malformed output, using the same recipe/model and sanitized
diagnostics. Do not retry refusals or truncation as output repairs. Failure in one
recipe does not erase successful siblings or prevent the remaining members running.

Retain available usage, cache-token counts, latency, request IDs, returned model,
actual mode and status for every call. Costs use the recipe's frozen pricing basis,
not future registry prices. The existing writer uses ordinary input/output rates
without special cache pricing; label that estimate and its limitations. Unavailable
usage/prices are unknown, not proof of zero cost (existing adapters sometimes return
zero token counts when metadata is missing; generalization must preserve that
distinction). Store measurement availability and estimate completeness.

Invocation totals count only calls from members generated in that invocation, plus
separately attributed assessment calls. Reused members have zero **new** generation
calls/cost; display their original cost/latency separately. Measure invocation wall
time independently of the sum of model latencies. Do not count earlier source-report
generation as this step's cost, or count reused results as independent observations.

## Optional assessment and human review

An assessment targets one exact successful comparison result and its frozen source,
using an explicit `verify` recipe. PR assessment receives the stored prepared PR
material, facts and omissions; aggregate assessment receives the exact supplied
report versions/query, not refreshed PRs or expanded source material. Freeze the
assessment's rendered target/source input and its hash. All source navigation is
attached by code. The assessment considers the whole result, without claim tables,
model-selected source lists or a numeric confidence field.

Define independence by the **underlying model**, not provider or registry key.
Store a canonical publisher/model/revision identity with an equivalence mapping and
evidence/policy version. Equivalent direct and routed aliases map to the same
identity and cannot assess each other independently. Different providers are not
evidence of different models. Unknown identity on either side fails independence
preflight (`independence_unknown`); there is no implicit override in M3. Known equal
identity fails with `same_underlying_model`. Different documented identities permit
assessment but do not promise uncorrelated errors. Compare returned-model metadata
to the frozen identity evidence; contradictions invalidate the independence claim
and leave assessment inconclusive, without changing the generated result.

Never substitute another assessor when the declared one fails independence or
budget checks. Missing assessment is the absence of an assessment invocation;
preflight/execution failure is a persisted failed assessment with errors; a valid
but undecidable verdict is inconclusive. None invalidates the generated result.
Assessment failure is not disagreement. Following #45, the new whole-result response
uses `agree`, `disagree` or `inconclusive` plus rationale; #45 owns the versioned
schema, rubric and prompt, and #47 owns human evaluation labels and adjudication. Store parsed
verdict/rationale separately from raw calls, with zero-or-more ordered attempt links,
the same bounded repair/accounting rules and independence evidence. M3 assessment
requests create new records; automatic assessment-result caching is out of scope.
Record the requesting invocation/member when assessment is part of a comparison;
a standalone assessment has its own request identity and is not charged to the
target result's historical origin invocation.

A human review identifies result ID, reviewer identifier, protocol ID/version/hash,
reader role, revision ID, previous revision ID, judgment/correction/rationale and
creation time. Reviewer identity is a study identifier, not an employee score or a
new account/authentication system. Preserve original output; corrections are linked
review artifacts, not edits to generated results. Reviews of reused outputs retain
the same result identity, with invocation/presentation context where relevant.

Use an append-only exposure event for each actual assessment reveal: review session,
reviewer, target result, exact assessment ID, event ordinal/time, and exposure kind.
Each review revision records the exposure events already seen; absence of a recorded
event alone must not assert blinding. Capture declared prior exposure (including
unknown/external exposure), presentation order and the initial pre-reveal judgment.
Reveals and post-reveal revisions never overwrite the blind judgment.

#47 must supply a concrete versioned payload for correctness, familiarity, usefulness,
preparation/reading/checking/correction effort, assessment-related effort, units,
missing measurements, post-reveal observations and adjudication before #42 finalizes
storage. A stored versioned evaluation document is acceptable for these fields; a
filename/hash without retained content is not. #48 implements capture; #50 obtains
real judgments. This ADR does not invent the rubric or claim synthetic reviews meet
the human evaluation requirement.

## Interface and relational storage sketch

Names below are proposed application interfaces, not current imports:

```text
create_recipe(name, registry_key, prompt, stage, settings) -> RecipeVersion
load_recipe(recipe_version_id) -> FrozenExecutionConfig
freeze_pr_source(snapshot_id, preparation_contract) -> ComparisonSource
freeze_aggregate_source(ordered_report_refs, query, preparation_contract) -> ComparisonSource
create_invocation(source_id, recipe_version_ids, force, retention, protocol_ref?) -> Invocation
find_comparison_result(source_id, recipe_version_id, execution_contract) -> Result | None
save_result(member_id, terminal_result, attempts) -> ResultId
reuse_result(member_id, result_id) -> Membership
assess_result(result_id, assessor_recipe_version_id) -> AssessmentId
append_review(result_id, reviewer_id, protocol_ref, revision, exposure_refs) -> ReviewId
record_exposure(review_session_id, result_id, assessment_id, event) -> ExposureId
```

The store owns database transactions; execution happens outside them. Frozen config
may reconstruct a one-model `Registry` for existing helpers, but that registry must
be built exclusively from the recipe. Generalize `save_calls` to a common attempt
contract for generation and assessment, with frozen settings/prices and availability
metadata. Keep parsed results in their own writer; return all call IDs, including
an empty tuple for zero attempts. Do not route through a live registry while saving.

| Proposed table | Principal keys, content and relationships |
|---|---|
| `output_schema_versions` | Unique stage/contract/version; immutable JSON Schema and hash, validator version; eligibility registry checked by application |
| `recipe_versions` | PK; unique name/version; stage, prompt FK, schema FK, frozen configuration/hash |
| `comparison_sources` | PK; kind, repository FK, optional snapshot FK, immutable source document/hash/preparation, query/altitude/scope |
| `comparison_source_inputs` | Source FK + ordinal PK; exactly one nullable FK to `pr_summaries` or `aggregate_reports`; unique input identity per source; stored rendered text/hash |
| `comparison_invocations` | PK; source FK; frozen specification, lifecycle and time metadata |
| `comparison_members` | Invocation FK + ordinal unique; explicit recipe FK; unique recipe per invocation; pending initially, then immutable generated/reused result link |
| `comparison_run_results` | PK; unique origin-member FK; source/recipe FKs; status, output/schema/hash, errors, cache identity and timestamps |
| `comparison_result_calls` | Result FK + positive ordinal PK; call FK unique; every attempt in order |
| `comparison_assessments` | PK; target-result and assessor-recipe FKs; requesting invocation/member or standalone request identity; frozen input, independence evidence, status, parsed verdict/rationale/schema, errors and timestamps |
| `comparison_assessment_calls` | Assessment FK + positive ordinal PK; call FK unique |
| `review_sessions`, `review_revisions`, `assessment_exposures` | Result/reviewer/protocol identity, retained protocol payload/reference, ordered exposure events and append-only review revisions with prior-revision/exposure FKs |

Use normal FKs and checks for reference existence, positive ordinals, stage/kind/status
enums and exactly-one input type; no opaque polymorphic IDs without relational links.
Use composite FKs or constraint triggers where necessary to ensure member/result
source and recipe agree, the origin member belongs to the origin invocation, a
reused result succeeded, review revisions/exposures share target/reviewer/session,
and assessment exposures point to an assessment of that same result. PR sources
require a snapshot and no aggregate input edges; aggregate sources require input
edges and no snapshot. Check repository agreement and exact input content in the
writer transaction, as M2 does. Cross-row cardinality/compatibility checks must be
enforced transactionally, with database constraints where expressible, not left to
the CLI. Keep stage/schema/prompt consistency and output-presence/status checks.

Each call belongs to only one attempt group, with matching stage, prompt, frozen
recipe settings and shared `generation_id`; order is contiguous and includes repair.
Enforce ownership across the generation and assessment link tables (a shared owner
constraint/table is acceptable). New comparison calls must not also belong to
production report groups. Reject reassignment. An FK to the final call alone is
insufficient. Store canonical result output as well as the schema reference; reads
under `hashes_only` must work without `response_text` or `request_payload`.

No new FK targets retired claim tables, `verifications` or `flags`. Preserve all
active M1/M2 history. Restrict deletion of referenced immutable history; no cascade
that erases result/source/review provenance. Prevent updates to frozen content through
storage APIs and database immutability guards. Do not reinterpret old records as M3
recipes without explicitly completing their missing configuration and provenance.

### Transaction and interruption boundaries

1. Save each recipe with its prompt/schema references atomically. Freeze source
   documents and ordered edges atomically; then save invocation and all pending
   recipe members together before calls. No remote call holds a database transaction.
2. Execute one member synchronously. In one transaction, validate the source and
   recipe, call the generalized `save_calls`, insert the terminal result and all
   attempt links, and finalize the member. Roll back this entire group on failure.
   A preflight failure uses the same transaction with zero calls. Successful result
   IDs and their contents cannot subsequently change.
3. A cache hit atomically validates and links the existing result and origin, then
   finalizes the membership as reused with zero new calls. Commit each member
   independently so one failed recipe does not roll back completed siblings.
4. Save an assessment and its attempt group independently of generation. Save a
   review revision and its exposure references atomically, rejecting mismatched or
   stale revision parents. Exposure events append in their observed order. Derive
   invocation totals/status from committed members; an unfinished member is not a
   fabricated failed call.

M3 remains synchronous. A process crash between a remote request and its database
commit can leave a pending member and an unrecorded billable request. A database
failure is not a successfully persisted failed-result record. Expose incomplete
invocations/accounting as such; do not claim complete recovered history. Durable jobs,
automatic retry/recovery and exactly-once execution are not required. A deliberate
new invocation can reuse already committed successes, or force new results; it does
not rewrite the interrupted invocation.

## Validation and downstream handoff

#41 adds only this proposed ADR and its index entry. Check Markdown links, whitespace,
and the design against current code and issue criteria. No live model call is needed.

Subsequent validation belongs to the implementation issues:

- **#47:** publish the review/protocol payload, missing-data and denominator rules,
  development/held-out split, and aggregate cases measuring the fixed single step.
  Supply these before storage is finalized; final output IDs and real judgments are #50.
- **#42:** add the next append-only migration (0007 if still next), result/source/
  recipe/review stores and integrity tests. Test fresh and populated-M2 upgrades,
  atomic migration markers, rollback of result/attempt groups, zero-attempt failures,
  reuse origins, wrong-stage/source/review links, and retained output/lineage/verdicts
  with full and `hashes_only` retention. Do not edit migrations 0001–0006.
- **#43:** test recipe versioning, registry/provider and prompt-file mutation/removal,
  executable stored content, schema/mode mismatches, unsupported implementations,
  secret exclusion, effective settings/pricing, and frozen execution round trips.
- **#44/#46:** test identical-source execution, one repair, no model substitution,
  SDK retry accounting, partial failures, force/reuse origins and costs, and production
  cache/current-report isolation in both directions. Baselines use the same contracts.
- **#45:** add whole-result assessment schema/prompt and tests for direct/routed
  equivalent models, unknown identity, budget/failure/inconclusive outcomes, retained
  verdicts and original-result preservation.
- **#48/#49/#50:** preserve human judgment and exposure revisions, inspect exact IDs,
  report new versus origin cost and incomplete measurements, then collect actual
  human evidence and complete the M3 demonstration/release. Offline tests and synthetic
  demos use controlled fixtures without paid calls.

## Decisions awaiting owner acceptance and remaining work

Recommend accepting the contracts above, particularly single-step aggregate scope,
fail-closed unknown-model independence, and separate result/reuse/review identity.
Single-step comparisons isolate composition on common inputs and reuse the existing
node generator; they do not measure whole-tree quality. Rejecting unknown identity
avoids calling a routed alias independent, at the cost of requiring documented model
identity before assessment. Disabling hidden transport retries makes attempted-call
accounting explicit, at the cost of less transient-error resilience in comparisons.

#47 still must choose the human rubric, effort fields, dataset and reviewer arrangement;
#45 must implement the assessment response schema, rubric and prompt. Those choices do not
authorize a storage migration or placeholder assessment recipe here. Record changes
to this proposal and affected issue text before dependent sessions use a different
contract. After acceptance, material reversals require a superseding ADR.

Session 1 integration branch: `milestone/3-different-models-measurable-results`.
Implementation branch: `docs/41-recipes-comparison-adr`. The linked PR records the
commit, checks and acceptance/handoff state. Keep #41 open until its acceptance
criteria and integration workflow are satisfied, and keep parent #6/main at the
completed M2 release until the whole M3 release is ready. Next session is #47 alone.
