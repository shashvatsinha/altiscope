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
`0010_comparison_execution_baselines.sql` are append-only. They preserve all M1/M2
rows, add nullable call measurement metadata and isolated M3 tables, and retain
underlying PR links for every frozen aggregate input. Whole-result assessment schema
registration remains owned by #45; this work does not invent an assessment recipe.

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
