# Altiscope

Altiscope builds organizational views of engineering work from what teams already produce
on GitHub: code changes, the reasoning written down alongside them, and the discussions
in which they were reviewed. Every statement it produces stays connected to the evidence
behind it. It is an evidence and provenance architecture in which language models do
bounded interpretation, not a summarizer with citations attached.

**Status: design and foundation stage.** The data model and the deterministic core are
implemented and tested; ingestion, the end-to-end model pipeline, verification and the UI
are not. [Status](#status) below has the specifics.

## The problem

Engineering organizations record their work in unusual detail. Every change to the code
arrives with an account of what it does, why it was made, and what the engineers who
reviewed it thought of it. Little of that survives the trip to the people who make
decisions about it: an engineer knows what their own changes did, a director knows what
someone told them after two rounds of human summarization. Each retelling loses
information and severs the link back to the evidence, so nobody downstream can check
anything, and a mistake gains authority as it travels.

Metrics do not close this gap, and not because they are bad. Cycle time and throughput
answer a question about quantity. "What actually changed, and why does it matter?" is a
question about content, and the answer lives in the code itself and in what the
reviewers said about it.

## The idea

Store the source material. Compute the numbers in code. Use a model to read a change and
describe it, but require that description to be typed claims, each pointing at specific
evidence. Check the pointers. Then compose claims on demand into views at whatever level
the reader needs — engineer, lead, manager, director, executive — while the path from any
sentence back toward its evidence stays intact.

```
merged change ──▶ snapshot ──▶ computed facts ──▶ claims + evidence  (model)
                                                        │
                                        validation ──▶ verification
                                                        │
        query {who, when, altitude} ──▶ synthesis  (model, on demand)
                                                        │
                                    provenance + coverage ──▶ reader ──▶ flags
```

## Why it might work now

A model can now read a change in full — the code, the description, the review discussion
— and produce a usable account of it. That is a real change in feasibility and not a
solution: a model that emits prose swaps an unauditable human summary for an unauditable
machine one, written fluently enough to hide the problem. Three ideas make the output
inspectable rather than authoritative.

*Provenance* records what each claim rests on, as rows and foreign keys. It does not
prove a claim correct; it makes the basis available so that something else can judge it.

*Verification* separates two checks. Deterministic validation asks whether a cited file,
quote or comment exists at all. A second model asks whether that evidence actually
supports the claim — a citation can point at real code and still misread it.

*Coverage* is the distinction most often missing. Provenance asks what supports this
statement; coverage asks how much of the work in scope contributed to this view. A
quarterly summary can be entirely well-evidenced and still mislead, because it described
two interesting changes and skipped the other forty. Every sentence survives scrutiny,
and the omission is invisible. Altiscope records the full set of work behind each view
and reports which of it no claim cited.

## Status

Implemented and tested: the Postgres schema and migration runner, the diff policy, fact
computation, prompt assembly, evidence validation, aggregate source validation, coverage,
the reduction-tree planner for windows larger than a model's context, the model registry
and router, adapters for the Anthropic API and for chat-completions endpoints, and
versioned prompts.

Not built: GitHub ingestion, the orchestration that calls a model and stores a summary,
verification, query resolution, the job worker, the API, the UI, authentication. There is
no golden set and no evaluation loop, so no claim here about output quality has been
tested. [`docs/ROADMAP.md`](docs/ROADMAP.md) is ordered.

## Learn more

- [THESIS.md](THESIS.md) — the argument and the hypotheses it rests on, including what it
  takes from Dorsey and Botha's
  [*From Hierarchy to Intelligence*](https://block.xyz/inside/from-hierarchy-to-intelligence)
  and what it deliberately does not claim.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the implementation: stages, schema,
  validation, routing, failure modes, open questions.
- [`docs/adr/`](docs/adr/) — individual decisions and the alternatives rejected.

## Development

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and Docker for Postgres.

```bash
uv sync --extra dev
docker compose up -d db
cp .env.example .env
uv run altiscope db migrate
uv run altiscope models list     # providers, models, per-stage routing
uv run pytest
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md). To change a decision, add a superseding ADR
rather than editing the existing one. Apache 2.0; see [`LICENSE`](LICENSE).
