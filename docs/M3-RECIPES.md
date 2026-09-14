# M3 recipes and comparison persistence

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
`0009_comparison_source_pr_links.sql` are append-only. They preserve all M1/M2
rows, add nullable call measurement metadata and isolated M3 tables, and retain
underlying PR links for every frozen aggregate input. Later
assessment schema registration and comparison execution are owned by #44/#45;
this storage layer deliberately does not invent an assessment recipe.
