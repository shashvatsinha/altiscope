# Thesis

Engineering organizations spend substantial effort explaining work that is already
recorded in code changes and review discussions. Altiscope's hypothesis is that these
records can support useful accounts at several levels of detail, with evidence that
readers can inspect, at less total effort than preparing those accounts manually.

## The cost of understanding work

“What changed in billing this month?” may require an engineer to reconstruct several
changes, a lead to connect them, and a manager to explain their significance. Each person
adds context, but each handoff takes time and can distance the reader from the evidence.

Later, someone questions a sentence in the report. They must find its author and repeat
part of the investigation. Another reader needs different dates or more detail, so the
account must be prepared again. Activity counts help describe how much happened;
understanding what happened still requires reading the work.

## One source, several useful accounts

Altiscope would start with GitHub pull requests: records that bring code changes,
explanations, and review discussions together. It would save a copy of each completed
change and use AI to describe it in statements linked to evidence.

Readers would select a team or repository, dates, and a level of detail. An engineer
could inspect how billing events are processed. A manager could follow the broader
billing changes. Both accounts would draw on the same sources, and readers could trace
a statement back to the material supporting it. The [README](README.md#what-it-would-look-like)
gives a fictional example.

The challenge is preserving meaning as the account gets shorter. Code can establish
that failed jobs are retried. It cannot, by itself, establish that customers experienced
fewer problems. A useful summary must respect that boundary.

## Why evidence matters

AI makes it possible to attempt the reading and writing in software. Altiscope's proposed
advantage is making the result easier to check, correct, and use in another account.

The application links each generated review to its source PR for human inspection.
A later independent model may assess the overall review against the changes. That
assessment can also be wrong; provenance remains useful regardless of its verdict.
Per-claim assessment is not planned.

Milestone 1 produces an overall code-based review with a deterministic PR association,
code-computed facts and disclosed input omissions. Interpretations remain unverified.
The [architecture](docs/ARCHITECTURE.md#4-reviews-and-publication) describes the contract.

## What could make this fail

The meaning of a change may depend on a customer conversation, a rejected design, or a
business priority that never appeared in its pull request. An accurate description of
code could still be too shallow to help a manager. Reviewing and correcting generated
accounts could also take as long as writing them.

If useful explanations routinely require unavailable context, the project needs a
broader evidence base. If a simpler summary saves just as much effort, the extra machinery
has not earned its cost. Altiscope is intended to describe work; these records are an
inadequate basis for evaluating employees.

## How to test the thesis

Begin with 20 real pull requests reviewed by people familiar with the work. Compare
human-written accounts, ordinary AI summaries, and Altiscope using the same source material.
Agree on success criteria beforehand and keep test examples separate from those used to
improve the AI instructions.

Measure three things:

- **Accuracy:** are statements supported, including after several changes are combined?
- **Usefulness:** do different readers get the detail they need, and does the second
  model catch meaningful errors without creating excessive review work?
- **Total effort:** how long does preparation, reading, checking, and correction take?

The first study can expose weaknesses. Demonstrating lasting savings requires a team
using the system over time. The complete workflow and these evaluations are still unbuilt.

## Inspiration

Dorsey and Botha's [*From Hierarchy to Intelligence*](https://block.xyz/inside/from-hierarchy-to-intelligence)
asks whether AI can take on information-sharing functions of organizational hierarchy.
Altiscope explores one limited application: making engineering work easier to understand
and its descriptions easier to check. The [roadmap](docs/ROADMAP.md) sets out the first steps.
