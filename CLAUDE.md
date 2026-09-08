# Working on Altiscope

Read `docs/ARCHITECTURE.md` before changing anything substantive. The ADRs in
`docs/adr/` record why things are the way they are; do not silently reverse one. If a
change needs a decision reversed, add a superseding ADR in the same PR.

## Ground rules that come from the product, not from taste

- Accuracy over breadth. A feature that could cause a summary to say something the
  source does not support is not a feature.
- The model never produces numbers; code computes facts. The model never emits database
  ids; it emits per-call opaque tokens the system maps back and validates.
- PR reviews link to their immutable PR snapshot and model call. M1 does not require
  claim citations or per-claim assessment; see ADR-0010.
- No evaluative language about people in any prompt or template.
- Prompts are versioned files under `prompts/`. Never edit one that has produced
  published output; add a new version.
- Nothing is pre-computed on a calendar. Aggregates are on-demand and cached by input
  set.

## Toolchain

- `uv sync --extra dev`, then `uv run ruff check .`, `uv run ruff format .`,
  `uv run pyright`, `uv run pytest`. CI runs all four plus integration tests against
  Postgres; keep them green.
- pyright is in strict mode. Do not loosen it; annotate.
- Schema changes are a new numbered file in `migrations/`. Never edit an applied one.
- Provider neutrality is a requirement, not a preference. Nothing outside
  `src/altiscope/llm/*_provider.py` may import a vendor SDK. New model support is a
  registry entry; new protocol support is one adapter file implementing `Provider`.
- Adapter notes. Anthropic: `client.messages.parse(..., output_format=Model)`, adaptive
  thinking, `output_config={"effort": ...}`, check `stop_reason` for `refusal`; ids
  without date suffixes. Chat-completions: `chat.completions.parse` in `native` mode,
  `response_format: json_object` in `json_mode`, prompted schema otherwise; report
  invalid JSON as `stop_reason="invalid_output"`, never raise.

## Where things are

- `src/altiscope/schemas/`: the LLM output contracts. Change them only with a
  `schema_version` bump.
- `src/altiscope/llm/router.py`: routing decision and its recorded reason.
- `src/altiscope/ingest/diff_policy.py`: what the model is and is not shown, and why.
- `src/altiscope/aggregate/planner.py`: the query-time reduction tree.
- `src/altiscope/aggregate/coverage.py`: cited vs. uncited inputs.
- `migrations/0001_initial.sql`: the provenance contract.

## Roadmap

`docs/ROADMAP.md` is ordered. Pick the top unfinished item unless told otherwise.
