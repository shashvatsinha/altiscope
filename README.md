# Altiscope

Engineering organizations spend substantial effort explaining work that is already
recorded in code changes and review discussions. Altiscope's hypothesis is that these
records can support useful accounts at several levels of detail, with evidence that
readers can inspect, at less total effort than preparing those accounts manually.

**Milestone 1 implementation is under review.** The CLI collects one public pull request,
stores its source, generates a code-based review linked to its PR and shows computed facts and omissions.
Interpretations are explicitly unverified.

[Read the example account](examples/m1/README.md) · [Run the walkthrough](docs/M1-WALKTHROUGH.md)

```bash
uv sync --extra dev --frozen
uv run altiscope demo
```

The credential-free demo uses a synthetic source and hand-authored recorded response.
The walkthrough also covers Postgres, live public-PR ingestion and opt-in model calls.

## What it would look like

A manager asks: **“What changed in billing this month?”**

Altiscope would read the relevant GitHub pull requests—the records of proposed code
changes and their review—and produce an account such as:

> Billing events now run in the background, with automatic retries when processing fails
> and checks for events received more than once.

An engineer could explore the implementation details. A leader could read a shorter
account of the changes. Both could follow the supporting statements back to the source.

*This is a fictional example.* Whether these changes reduced incidents or improved
customer outcomes would require further evidence.

## The approach

Altiscope would save the source material, use AI to review each PR, and link the
review back to that PR for human inspection. A later independent model may assess the
overall review. Readers would choose
people, teams, or repositories, a date range, and a level of detail.

The aim is an account that is easier to check and reuse. Its accuracy and usefulness
still need to be tested on real work.

## Explore or contribute

The first workflow connects public-PR collection, immutable snapshots, provider-neutral
generation, PR provenance and CLI inspection. Aggregation, semantic verification,
organization access and a user interface remain future milestones.

- [Thesis](THESIS.md): why this is worth trying and how to test it.
- [Architecture](docs/ARCHITECTURE.md): how the parts fit together.
- [Roadmap](docs/ROADMAP.md): what comes next.
- [Contributing](CONTRIBUTING.md): setup and development instructions.

Open source under [Apache 2.0](LICENSE).
