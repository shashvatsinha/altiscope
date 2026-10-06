# M3 recipes and comparison execution

M3 recipes are immutable, named versions of one resolved generation configuration.
The recipe stores the complete prompt source, output schema document, provider
endpoint, model wire name and underlying-model evidence, capabilities, effective
generation settings, input budget, pricing basis, and implementation versions.
Execution can therefore load a recipe after the registry or prompt file changes.
Secrets are never copied; `credential_reference` contains only the configured
environment/profile name.

Apply the append-only migration before using the commands:

```bash
altiscope db migrate
```

Save and inspect recipes with the CLI. Saving an unused name creates version 1;
saving the same name appends another version.

```bash
altiscope recipes save monthly-pr --stage pr_summary --model openrouter-anthropic
altiscope recipes save monthly-pr --stage pr_summary --model openrouter-anthropic \
  --effort low --reserved-output-tokens 8192
altiscope recipes list
altiscope recipes show monthly-pr --version 1
```

The Python API used by comparison execution is:

```python
recipe = create_recipe(
    conn,
    name="monthly-pr",
    registry_key="openrouter-anthropic",
    prompt=latest_prompt(prompts_dir, "pr_summary"),
    registry=registry,
    overrides=RecipeOverrides(effort="low"),
)
loaded = load_recipe(conn, recipe.id)
frozen_registry = loaded.config.to_registry()
```

`freeze_pr_source` and `freeze_aggregate_source` retain prepared source text and
its hash. `create_invocation` freezes the ordered recipe members. A member is
finalized by `save_result` with its parsed output and every real attempt, or by
`reuse_result` with an explicit origin and zero new calls. `hashes_only` removes
request/response payloads from calls but does not remove validated result output.
Comparison records use a separate `comparison` cache namespace and never update
production `pr_summaries` or `aggregate_reports`.

The evaluation module retains versioned protocol/dataset/record-contract artifacts,
exact-result review sessions, effort measures, append-only revisions, and ordered
assessment exposure events. A guided assessment reveal is rejected until the initial
review revision is committed.

Migrations `0007_comparison_persistence.sql` through
`0013_optional_review_rationale.sql` are append-only. They preserve all M1/M2
rows, add nullable call measurement metadata and isolated M3 tables, and retain
underlying PR links for every frozen aggregate input. The published verify v2 prompt
and `altiscope.whole_result_assessment` schema are the executable whole-result
assessment contract; the retired claim-level verify v1 contract is ineligible.

## Run a comparison

First freeze a source through `freeze_pr_source` or `freeze_aggregate_source`. The
former accepts one immutable saved PR snapshot and its preparation; the latter
accepts an ordered, nonempty set of exact successful saved report versions, the
query, altitude, and the already-rendered single-step request. Source preparation
happens once. Comparison execution never refreshes GitHub, selects newer reports,
or builds a hidden aggregate tree.

Register the ordinary minimal prompt as each candidate recipe's primary baseline.
The command creates a prompt-only immutable variant, or shares an existing variant
when the complete non-prompt generation condition is identical:

```bash
altiscope recipes baseline 11111111-1111-1111-1111-111111111111
altiscope recipes baseline 22222222-2222-2222-2222-222222222222
```

The shipped baseline prompts are `prompts/baseline/pr_summary-v1.md` and
`prompts/baseline/aggregate-v1.md`. They use the same output contracts and preserve
the prohibition on evaluating people. Their recorded rationale is that the model,
endpoint, schema, generation settings, input preparation, and aggregate scope are
held fixed while the prompt becomes an ordinary minimal summary request.

Run at least two explicit, exact recipe versions against the frozen source. Assigned
primary baselines are included by default and deduplicated before the invocation is
saved, including a baseline already listed explicitly:

```bash
altiscope comparisons run SOURCE_UUID \
  --recipe 11111111-1111-1111-1111-111111111111 \
  --recipe 22222222-2222-2222-2222-222222222222
```

Use `--regenerate` to bypass successful comparison results and create new immutable
results. Use `--no-baselines` only for an explicitly unbaselined engine run. A normal
rerun reuses successful compatible results with zero new calls; failed results are
not cached. The command labels prompt-only baselines separately from explicit recipes
that change the model condition. It reports current calls, current configured-price
cost estimates, independent wall time, and historical origin figures for reused
results. Missing usage or price information is reported as unavailable, never zero.

Each recipe runs once with at most its one configured malformed-output replacement.
Complete-request budgets include system text, the exact frozen user text, schema, and
envelope allowance. Oversized and credential failures have zero calls. A failed member
does not remove successful siblings. Comparison adapters use zero hidden transport
retries, and comparison results never become production-current reports.

The comparison service is also available as `altiscope.comparison.run_comparison`.
Tests inject `FixtureProvider` instances into its `provider_factory`, so the complete
workflow is exercised offline without live or paid model calls.

Primary baselines are controls for the observed recipe outputs, not proof that one
prompt caused a difference in a stochastic sample. M3 intentionally has no numeric
confidence fields. Confidence reporting would require a separately specified sampling
and evaluation method; the M3 protocol instead reports case-level counts, medians,
ranges, missingness, and limitations.

Configured-price estimates rate ordinary input, output, cache-read, and cache-write
tokens separately. Cache rates are optional registry data because availability and
price vary by model and provider. If a call reports cache usage without the matching
frozen cache rate, its cost and the containing comparison total are unavailable; the
system never substitutes the ordinary input rate.

## Run an independent whole-result assessment

Save an explicit `verify` recipe using the published v2 assessment prompt, then target
one exact successful comparison result:

```bash
altiscope recipes save independent-assessor --stage verify --model openrouter-openai
altiscope comparisons assess RESULT_UUID --recipe VERIFY_RECIPE_UUID
```

Assessment execution never calls the production router and never substitutes another
model. It compares the producer and assessor recipes' frozen canonical underlying-model
identities, failing closed when either identity is unknown or both are equivalent (for
example, direct Anthropic and an OpenRouter alias of the same Anthropic model). It sends
the assessor the target's retained validated output plus the exact frozen preparation and
prepared source text. It does not refresh GitHub, select newer reports, or trim evidence.
An oversized or unavailable complete source creates a persisted zero-attempt failure.

Every request creates a new immutable assessment record. Every actual initial or repair
call is attached to that request and priced from the assessor recipe's frozen basis. The
original generated result remains valid regardless of assessment outcome. Absence of a
record means `not_run`; stored outcomes distinguish `succeeded`, `inconclusive`, and
failure statuses. The command hides a completed verdict and rationale by default so a
future human-review workflow can collect its initial judgment first. Use `--reveal` only
after that judgment; hiding output cannot undo exposure that happened elsewhere.

The Python API is `altiscope.assessment.run_assessment`. Consumers can load immutable
history with `altiscope.store.comparisons.list_assessments` and render a specific record
with `altiscope.assessment.render_assessment(assessment, reveal=False)`. Rendering `None`
returns an empty string, preserving normal output when assessment has not run.

## Record a human review

Start the guided workflow with one exact successful result ID. It retains the checked-in
protocol, dataset, and record-contract content, records reviewer role and familiarity,
shows the frozen source before the result, reuses preparation once per reviewer/case/source,
and collects correctness, usefulness, and millisecond effort with explicit measured,
not-applicable, or unavailable states.

```bash
altiscope comparisons review RESULT_UUID \
  --reviewer reviewer-t1 \
  --case-id m3-dev-pr-001 \
  --case-group development \
  --familiarity domain \
  --familiarity-basis "Python document-conversion review experience"
```

The command commits the immutable initial revision and stops with assessment output hidden.
If an assessment exists, reveal it through the review session. The exposure event is saved
before the verdict or rationale is printed; a guided reveal without an initial revision is
rejected by storage.

```bash
altiscope reviews reveal REVIEW_SESSION_UUID ASSESSMENT_UUID
altiscope reviews observe REVIEW_SESSION_UUID EXPOSURE_UUID --revise-judgment --complete
```

`reviews observe` records result-level detections, false alarms, misses or inconclusive
outcomes, assessment-related effort, post-assessment usefulness, and an optional append-only
judgment/correction revision. It does not edit the generated result or regenerate production
output. Failed and inconclusive assessments remain distinct; no assessment record is
reported as `not_run`.

Resume or hand off a session without conversation history:

```bash
altiscope reviews resume REVIEW_SESSION_UUID  # if initial capture was interrupted
altiscope reviews show REVIEW_SESSION_UUID
altiscope reviews export REVIEW_SESSION_UUID --output review.json
```

The normal view reveals only assessment records whose exposure is already persisted for
that session. `--json` and `export` produce the complete `m3-review-record-v1` document,
including retained artifact content, exact result/source IDs, historical PR navigation,
zero-versus-missing effort, presentation order, revisions, exposures, and observations.
These local commands do not add authentication or access control; concealment supports the
evaluation sequence and cannot undo exposure through another path.

## Inspect a saved comparison

Use the invocation ID printed by `comparisons run` or the offline example below:

```bash
altiscope show-comparison INVOCATION_UUID
altiscope show-comparison INVOCATION_UUID --verbose
```

Every declared recipe appears in its original order, including a failure or pending
member. The view shows the exact frozen source and recipe identities, prompt and schema
versions, provider and underlying model, baseline membership, retained output or error,
and historical input report IDs and PR links. For aggregate inputs, use the printed
`show-report` or `show-aggregate` command to inspect each saved version. `--verbose`
adds the complete prepared input, resolved recipe config, and prompt source.

Generation and independent-assessment calls, token usage, cost estimates, latency,
repairs, and current invocation spend are labeled separately. A reused result shows
its original result and cost but zero new calls and no new model spend. Missing usage,
cost, or latency is printed as unavailable. The one-step comparison has no aggregate
tree-node accounting.

Assessment status is visible, but its verdict and rationale stay hidden in this view.
After an initial judgment is committed, reveal an assessment through the review
workflow, which saves the exposure before displaying the verdict. Then inspect with
that exact session ID to see only assessments exposed in that session:

```bash
altiscope reviews reveal REVIEW_SESSION_UUID ASSESSMENT_UUID
altiscope show-comparison INVOCATION_UUID --review-session REVIEW_SESSION_UUID
```

## Credential-free create, run, inspect, and review walkthrough

From the repository root, start Postgres, set `ALTISCOPE_DATABASE_URL`, and apply
migrations as in the [M2 walkthrough](M2-WALKTHROUGH.md). Then run:

```bash
uv run python examples/m3/offline_flow.py
```

The script saves a synthetic PR snapshot, freezes its prepared source, saves two
immutable fixture recipes and their prompt-only baselines, and runs all four with
recorded responses. It makes no network or paid model call. It prints the source,
invocation, recipe, and exact result IDs. Use the printed `show-comparison` command
to inspect them. Use the printed `comparisons review` command to record a development
review of one exact result; it prompts for correctness, usefulness, and each effort
measure. Save the resulting review session ID, then verify persistence with:

```bash
altiscope reviews show REVIEW_SESSION_UUID
altiscope reviews export REVIEW_SESSION_UUID --output /tmp/m3-offline-review.json
```

The script's synthetic output and any judgment about it are workflow checks only.
The real-source demonstration and later qualified evaluation are tracked in #50
and [ADR-0013](adr/0013-m3-workflow-release-scope.md).

For the separate issue #50 demonstration, run
`uv run python examples/m3/synthetic_study.py` to persist two recipes and their
prompt-only baselines on both a synthetic PR and a manager aggregate. It also
persists an independent disagreement assessment and a clearly labeled simulated
review/export. After ingesting development PR #19, add `--pilot-pr19` to exercise
the same sequence on a real saved source with hand-authored responses. Neither
run measures live model quality or qualified human correctness. The
[workflow plan](evaluation/m3-workflow-plan.md) records the live OpenRouter setup,
saved IDs, budget gate, and remaining release work.
