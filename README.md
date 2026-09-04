# Altiscope

Altiscope constructs organizational views of engineering work from pull requests, where
every statement remains connected to the evidence that produced it. It is an evidence and
provenance architecture in which language models perform bounded interpretation steps,
not a summarizer with citations attached.

**Status: design and foundation stage.** The data model and the deterministic core are
implemented and tested; GitHub ingestion, the end-to-end model pipeline, verification and
the UI are not built. [Status](#status) below has the specifics.

## The problem

Engineering organizations record their work in unusual detail. Pull requests carry the
change, the reasoning behind it, and the discussion of whether it was right, all
timestamped and available through an API.

Very little of that record survives the trip to the people who make decisions about it.
An engineer knows what their pull requests did; their lead knows roughly what the team
did; a director knows what someone told them, after two rounds of summarization performed
by people with incomplete visibility and limited time. Each retelling loses information,
and the connection back to the underlying evidence is gone — so nobody downstream can
check anything, and a mistake acquires authority as it travels.

Engineering metrics do not close this gap, and not because they are bad. Cycle time,
throughput and change failure rate answer a question about quantity. "What materially
changed, and why does it matter?" is a question about content, and the information needed
to answer it lives in diffs and review threads rather than in counts. Both are useful;
they are not substitutes.

## The idea

Start from engineering artifacts, initially GitHub pull requests. Store the source
material. Compute the numbers in code. Use a model for reading a change and describing
what it does, and require that description to take the form of typed claims, each
pointing at specific evidence in the stored material. Check those pointers. Then compose
the claims, on demand, into views at whatever level of abstraction the reader needs,
keeping the path from any sentence back toward its evidence intact.

```
merged PR ──▶ stored snapshot ──▶ computed facts + filtered diff
                                            │
                                            ▼
                             claims with evidence pointers  (model)
                                            │
                              validation ──▶ verification  (deterministic, then model)
                                            │
                                            ▼
              query {who, when, altitude} ──▶ synthesis  (model, on demand)
                                            │
                                  provenance + coverage ──▶ reader ──▶ flags
```

Models interpret and synthesize inside that chain. They do not contribute numbers,
database identifiers, or authority.

## Why this may be tractable now

Reading a diff and saying what it means used to require an engineer, which made the cost
of interpretation scale with the volume of work. That is why organizations push the task
down to whoever is closest to it and absorb the losses from each retelling.

Current models change that economics: one can read a complete pull request and produce a
usable account of it, and long contexts mean a bounded artifact can be read whole rather
than sampled. This is a real change in feasibility, and it is not sufficient on its own.
A model that emits prose replaces an unauditable human summary with an unauditable
machine one, produced fluently enough to disguise the problem.

Three ideas do the work of making model output inspectable rather than authoritative.

**Provenance** records what each claim rests on, as rows and foreign keys rather than
text. It does not establish that a claim is correct; it makes the basis of the claim
available, which is what allows anything else to evaluate it.

**Verification** distinguishes two different checks. Structural validation is
deterministic: does this file exist in the snapshot, is this quoted span really in the
description, is this comment one the model was shown. Semantic verification asks a
different model whether the cited evidence actually supports the claim — because a
citation can point at real code and still misread it.

**Coverage** is not the same as provenance, and the difference matters more than it first
appears. Provenance asks what supports this statement. Coverage asks how much of the work
in scope contributed to this view. A quarterly summary can consist entirely of
well-evidenced claims and still mislead, because it wrote about the two interesting pull
requests and skipped the other forty. Every sentence survives scrutiny; the omission is
invisible. Altiscope records the full input set for every view and reports which inputs
no claim cited, next to the narrative.

## Reader altitude

The same evidence base should support different levels of synthesis, chosen when the
question is asked: an engineer wants technical specifics, a lead wants workstreams, a
manager wants their state, a director wants themes across teams, an executive wants a few
statements each resting on a large share of the work. Today these are written by
different people at different times from different partial knowledge, which is why they
routinely disagree. Higher altitude should mean more synthesis over the same facts — not
a different factual universe, and not weaker grounding.

## Design in brief

- The merged pull request is the atomic unit: bounded, semantically rich, already
  reviewed, and a one-time event that makes a natural cache key.
- Source material is snapshotted before interpretation, so summaries are reproducible and
  evidence pointers stay valid regardless of what happens to the repository later.
- Facts are computed in code and kept separate from model interpretation, so a summary
  cannot misquote a number.
- Interpretation is structured: typed claims carrying evidence pointers, validated before
  storage.
- Views are composed at query time over any subjects and any date range. There are no
  scheduled rollups, so no reporting calendar is imposed on the reader, and provenance is
  preserved through every intermediate level of synthesis.
- Model choice is configuration, recorded on every call with the reason it was routed
  there.
- The system describes engineering work. It is not designed to evaluate employees;
  [THESIS.md](THESIS.md) explains why pull request evidence is a poor basis for that.

## Status

This is a design-stage project with a tested foundation, not a working system.

Implemented and tested: the Postgres schema and migration runner; the diff policy; fact
computation; prompt assembly and the opaque-token scheme that keeps database identifiers
away from the model; structural validation of evidence pointers; aggregate source
validation and coverage; the reduction-tree planner for windows that exceed a model's
context; the model registry and router; adapters for the Anthropic API and for any
endpoint speaking the chat-completions protocol; versioned prompts with content hashes.

Not built: the GitHub client (the interface exists, no implementation does); the write
path into the snapshot tables; the orchestration that calls a model and stores a summary;
the verification stage; query resolution and aggregate caching; the job worker; the API,
the UI, and authentication. There is no golden set and no evaluation loop, so no claim in
this repository about output quality has been tested.

[`docs/ROADMAP.md`](docs/ROADMAP.md) is ordered, and the open questions in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) should be settled before much of it is
built at scale.

## Learn more

- [THESIS.md](THESIS.md) — why the approach may work, the distinctions it depends on, and
  the hypotheses it rests on. It takes up Dorsey and Botha's
  [*From Hierarchy to Intelligence*](https://block.xyz/inside/from-hierarchy-to-intelligence)
  on hierarchy as an information-routing mechanism, and why Altiscope is a much narrower
  exploration of one implication of it.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the proposed implementation: pipeline
  stages, schema, validation, routing, aggregation, failure modes, open questions.
- [`docs/adr/`](docs/adr/) — individual decisions and the alternatives rejected.

## Development

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and Docker for Postgres.

```bash
uv sync --extra dev
docker compose up -d db
cp .env.example .env
uv run altiscope db migrate
uv run altiscope models list                    # providers, models, per-stage routing
uv run altiscope models route pr_summary --input-tokens 120000
uv run pytest
```

`ALTISCOPE_MODELS_CONFIG=config/examples/ollama.yaml` switches to a fully local layout;
`config/examples/` also has OpenAI-only and mixed-vendor registries.

See [`CONTRIBUTING.md`](CONTRIBUTING.md). To change a decision, add a superseding ADR
rather than editing the existing one.

## License

Apache 2.0. See [`LICENSE`](LICENSE).
