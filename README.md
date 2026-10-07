# Altiscope

Altiscope helps managers and executives answer **“What did my teams build?”**
It explains what the code changes do in simple language, using merged GitHub pull
requests as the source. PR descriptions and discussions provide context; the code
changes ground the account. People can judge alignment with their own intentions;
Altiscope does not ingest a desired direction or evaluate employees.

**Repository summaries are implemented.** The CLI collects
merged PRs for a date window, summarizes their saved reports, and lets readers drill
down to the exact reports and GitHub PRs used. It preserves model, prompt, and version
history. M2 includes the code-review fixes and the engineer and manager examples
accepted by the owner for inclusion. See the [release evidence](docs/releases/m2.md).

[Read the billing examples](examples/m2/README.md) · [Run the M2 walkthrough](docs/M2-WALKTHROUGH.md)

```bash
uv sync --extra dev --frozen
uv run altiscope demo --stage aggregate --altitude manager
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
account of the changes. Both could open the underlying PR reports and follow their links to GitHub.

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

The first workflow collects a public PR, saves its source, generates a report, and
lets you inspect it in the CLI. It keeps the model and prompt details and earlier
report versions. M2 combines those reports with drill-down to their exact input versions. M4 will bring this workflow to a local web interface on your laptop or desktop,
using your server-side GitHub token for accessible public and private repositories.
M5 will add public hosting, login, and users connecting their own repositories.
See [ADR-0014](docs/adr/0014-local-web-and-hosted-access.md).

- [Thesis](THESIS.md): why this is worth trying and how to test it.
- [Architecture](docs/ARCHITECTURE.md): how the parts fit together.
- [Roadmap](docs/ROADMAP.md): what comes next.
- [Contributing](CONTRIBUTING.md): setup and development instructions.

Open source under [Apache 2.0](LICENSE).

M3's immutable recipe and reproducible comparison commands are documented in
[`docs/M3-RECIPES.md`](docs/M3-RECIPES.md). They retain frozen prompts, schemas,
provider/model settings, source inputs, result attempts, and review records without
changing production report history. Prompt-only primary baselines are included by
default and are labeled separately from model-changing comparisons. M3 can
also run an optional whole-result assessment with a distinct pinned underlying model;
its output is stored separately and hidden by default for pre-judgment workflows. A
guided exact-result review records correctness, usefulness, human effort, corrections,
and actual assessment exposure without changing generated outputs.
`altiscope show-comparison INVOCATION_UUID` inspects every saved PR or aggregate
recipe result, historical inputs, costs, and review status. See the credential-free
[M3 walkthrough](docs/M3-WALKTHROUGH.md) and [workflow example](examples/m3/README.md).
M3's release demonstration tests this workflow on a bounded set of real PRs and
one manager aggregate. It does not claim a qualified quality result. Qualified evaluation remains optional future work using fresh held-out cases; it
is not an M4 or M5 release gate. See [ADR-0014](docs/adr/0014-local-web-and-hosted-access.md).
