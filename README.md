# Altiscope

Altitude-appropriate visibility into engineering work, sourced from GitHub pull requests,
with structured provenance for every claim.

**Status: design stage.** The architecture, data model, model-routing registry and the
pure-logic core (diff policy, routing, claim validation, aggregation planning) exist and
are tested. Ingestion, the LLM pipeline end to end, and the UI are not built yet. Read
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) first; it is the proposal this repository
is built against, and it ends with the open questions that still need an owner's answer.

## The problem

Engineering organizations are hierarchical. Individual contributors and leads do the
work; each layer above exists partly to compress what happened into the right level of
detail for the next layer. That compression is manual, slow, inconsistent, and
unverifiable. When it is wrong, it is wrong with authority.

## What Altiscope does

1. Ingests merged pull requests from GitHub (a GitHub App for organizations, a token for
   evaluation), storing an immutable snapshot of description, full diff, review threads
   and commits.
2. Summarizes each PR once with an LLM into **typed claims with evidence pointers**, plus
   facts computed in code, plus an explicit list of what the model was not shown.
3. On demand, for any people/teams/repositories over any date range at any reader
   altitude, composes those atomic summaries into a narrative whose every claim cites the
   source claims behind it, as rows in a table, not as prose.
4. Reports **coverage**: which PRs in the window the narrative cited and which it did
   not, so selective emphasis is visible.
5. Lets readers verify any claim against its source and flag misrepresentation. Flags
   feed a regression set that gates prompt and model changes.

The name is a double meaning: altitude (the right level of detail for who is reading) and
scope (an instrument for close examination). A plausible later direction is
quality, security and compliance checks against engineering standards. That is not built,
and the data model is chosen so it would not require a rewrite.

## Design principles

1. The **pull request**, not the commit, is the atomic unit of work.
2. Each PR is **summarized once** and cached until the prompt, schema or model changes.
3. Every higher-level view is **generated at query time** from atomic summaries in the
   window. No pre-computed rollups; the date range is free.
4. **Provenance is structured data.** Every claim traces to specific PRs through foreign
   keys. Drill from "the team shipped X this quarter" to the hunk.
5. **Model choice is a routing decision** driven by a config registry, not a hardcoded
   dependency.
6. Every summary records **which model produced it and why** it was routed there.
7. **Accuracy over breadth.** A wrong summary reaching a manager's manager is worse than
   none. The system must be self-testable by the teams it describes.

And one thing not to do: no retrieval or embedding search to squeeze a PR into a small
window. A PR is bounded; it is read whole.

## Technology decisions

Each of these has a fuller record in [`docs/adr/`](docs/adr/).

| Choice | Why, briefly |
|---|---|
| **Python 3.11+, pyright strict, pydantic v2** | The hard problems are prompt design, structured-output validation and evaluation, where Python's LLM tooling is strongest. Strict typing and pydantic at every model boundary keep it honest. Go's deployment story and TypeScript's UI story were both considered and judged to optimize the wrong part of this system. |
| **Postgres only, hand-written SQL migrations** | The schema is the provenance contract and should be readable as SQL. `CHECK` constraints enforce that every claim source points at exactly one real row. Supporting SQLite too would mean a second dialect to verify every provenance query against. |
| **GitHub App for ingestion, polling first, webhooks later** | Least-privilege, short-lived tokens, GHES-compatible, and an identity a security team can approve. Polling always works; webhooks are a freshness optimization that never replaces reconciliation. |
| **Snapshots stored, summaries computed from snapshots** | Reproducible summaries with evidence pointers that stay valid regardless of what happens to the repository later. |
| **Any model, via a YAML registry and two adapters** | Enterprises mandate providers, and some allow nothing outside their network. A native Anthropic adapter plus one chat-completions adapter cover Claude, GPT, Azure, and open-source models on Ollama, vLLM, llama.cpp or LM Studio; providers are endpoints, declared as many times as needed. Models declare capabilities and the adapter falls back from schema-enforced to prompted JSON; validation against the snapshot is the guarantee either way. Routing by fit with a recorded reason gives empirical model comparison on real output. A multi-provider abstraction library was rejected for its uneven structured-output support. |
| **Second-model verification, default on** | Roughly doubles per-PR cost, once. It is the cheapest strong signal available for the property the system exists to provide. |
| **Query-time reduction tree for large windows** | Honors "no pre-computed rollups" while fitting in a context window. Intermediates are stored with their own provenance so drill-down works at every level. |
| **Postgres-backed job queue** | PRs merge at human pace. A second queue system is not justified by the throughput. |
| **Server-rendered UI (FastAPI + templates) for v1** | Keeps one language while the hard problems are solved; the JSON API is the contract a richer front end can consume later. The most reversible decision in the list. |

## Layout

```
config/models.yaml        model registry and per-stage routing
prompts/<stage>/vN.md     versioned prompts; hash recorded on every call
migrations/*.sql          schema, applied in order
src/altiscope/
  schemas/                pydantic models for summaries, claims, evidence, aggregates
  llm/                    registry, router, provider protocol, Anthropic adapter
  ingest/                 GitHub client interface, snapshot types, diff policy
  summarize/              facts, prompt assembly, output validation
  aggregate/              window planning (reduction tree), coverage, validation
  store/                  database access and migration runner
  cli/                    `altiscope` command
docs/ARCHITECTURE.md      the proposal
docs/adr/                 decision records
docs/ROADMAP.md           what comes next, in order
```

## Getting started (development)

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and Docker (for Postgres).

```bash
uv sync --extra dev
docker compose up -d db
cp .env.example .env            # fill in what you have
uv run altiscope db migrate
uv run altiscope models list    # show providers, models, routing
# Other layouts: ALTISCOPE_MODELS_CONFIG=config/examples/ollama.yaml (fully local)
uv run altiscope models route pr_summary --input-tokens 120000
uv run pytest
```

There is no end-to-end pipeline yet. See the roadmap.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Design discussion happens in ADRs; if you
disagree with a decision, open a PR that adds a superseding ADR rather than editing the
old one.

## License

Apache 2.0. See [`LICENSE`](LICENSE).
