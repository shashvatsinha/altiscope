# Altiscope

Engineering organizations spend substantial effort explaining work that is already
recorded in code changes and review discussions. Altiscope's hypothesis is that these
records can support useful accounts at several levels of detail, with evidence that
readers can inspect, at less total effort than preparing those accounts manually.

**Early development.** The foundations exist; the complete system and user interface
are still to be built.

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

Altiscope would save the source material, use AI to describe each change, check the
references, and ask a second model to review the interpretation. Readers would choose
people, teams, or repositories, a date range, and a level of detail.

The aim is an account that is easier to check and reuse. Its accuracy and usefulness
still need to be tested on real work.

## Explore or contribute

The code includes the database design, reference checks, summary planning, and connections
to AI models. Automatic GitHub collection, the complete reporting workflow, and the
interface remain unfinished.

- [Thesis](THESIS.md): why this is worth trying and how to test it.
- [Architecture](docs/ARCHITECTURE.md): how the parts fit together.
- [Roadmap](docs/ROADMAP.md): what comes next.
- [Contributing](CONTRIBUTING.md): setup and development instructions.

Open source under [Apache 2.0](LICENSE).
