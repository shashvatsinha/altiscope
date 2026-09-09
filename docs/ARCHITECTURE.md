# Architecture

Altiscope helps readers understand engineering work by summarizing merged GitHub
pull requests (PRs). It first writes a report for each PR, then combines those
reports into broader summaries. Readers can follow a summary down to the reports
it used and eventually open the original PRs on GitHub.

For example, “What changed in billing this month?” would select the relevant PR
reports for that month and summarize them for an engineer, manager, or executive.
The model writes the explanation. The application records which reports it read.

## 1. Implementation status

**M1 implements the single-PR workflow. M2 now implements repository summaries.**
M2's code and repeatable demos are ready for review; human sample review and release
integration remain pending. See the [M2 walkthrough](M2-WALKTHROUGH.md) and
[release evidence](releases/m2.md).

| Workflow | Available now |
|---|---|
| Source collection | Save public PRs and refresh merged PRs within an inclusive date window |
| PR reports | Generate and save reports, preserving earlier source and report versions |
| Combined reports | Route and execute single- or multi-level summaries, with cached results |
| Inspection | CLI drill-down through exact input versions to PR reports and GitHub links |
| History | Shared prompt/model-call records, with new versions created on request |
| Demonstration | Credential-free engineer, manager, executive, and multi-level examples |

The [M1 walkthrough](M1-WALKTHROUGH.md) covers individual PR commands. The
[roadmap](ROADMAP.md) covers later work, including a web interface and model evaluation.

## 2. From source to report

The single-PR workflow is:

```text
GitHub PR → saved copy of the PR → prepared model input → generated PR report
                                                        ↓
                                           saved model and prompt details
```

`ingest owner/repo NUMBER` saves the PR. `summarize owner/repo NUMBER` generates
from a saved, merged PR. `show owner/repo NUMBER` displays its current report.
`demo` uses a synthetic PR and a recorded response; it makes no live model call.
`demo --persist` also exercises database storage.

The combined-report workflow builds on those reports:

```text
PR reports → summaries of groups, if needed → final summary
```

If all reports fit in one model request, no intermediate summaries are needed.
If they do not fit, the planner groups them, summarizes each group, and repeats
until the resulting reports fit. Each saved result links to the specific
versions immediately below it. Readers can inspect those reports or view all
underlying GitHub PR links.

## 3. Saving and preparing the source

Altiscope saves the PR description, code changes, commits, reviews, and comments
in Postgres. A saved copy is a **snapshot**: later GitHub edits create a new version
instead of changing the source of an older report. Unchanged content reuses the
existing snapshot. Raw responses and collection times are also retained.

Collection follows GitHub pagination and checks file and commit counts. It rejects
results when those checks fail or when it detects the PR changing during collection.
GitHub endpoints do not provide a single atomic read, so this cannot detect every
possible concurrent edit. Public access works anonymously or with a personal access
token; organization access through a GitHub App is planned.

Before generation, code calculates facts such as counts and decides which patches
fit the input policy. Generated files, dependencies, missing patches, and oversized
text may be excluded. The saved **input manifest** lists those exclusions and the
policy used. An old report displays its saved facts and exclusions even if the
policy later changes. Comments are presented in a stable order.

## 4. Reviews and publication

A PR report is an overall explanation of a code change. Patches are the main input;
the description and discussion provide context. The application attaches the source
PR and generation record. The model does not produce citations for individual
sentences. See [ADR-0010](adr/0010-pr-review-provenance.md).

The application checks that the response has the required format and nonblank text.
It allows one retry for malformed output. A refusal, truncated response, or transport
failure does not replace a usable report. Here, “published” means saved as the current
usable report; it does not mean posted to an external service.

These checks do not establish accuracy. Readers can inspect the underlying material,
and the CLI currently labels interpretation as unverified. Prompts ask the model to
describe work without judging people. Optional independent review and evaluation
remain later work.

## 5. Answering a reader's question

M2 adds a repository, date range, and reader level: engineer (`ic`), manager, or
executive (`exec`). The same source reports can support different amounts of detail.
For a new summary, the default is the latest successfully generated reports
from the level below. Manual version selection can come later.

The model summarizes the supplied text. The application records **all** supplied
report versions and all underlying PR links. A source need not be mentioned by name
to appear in drill-down. There is no model-selected source list or coverage percentage.
The list answers “What went into this summary?”; it does not score the writing.

## 6. Keeping results traceable

**Provenance means the history needed to investigate a report:** its source material,
its input reports, and which model and prompt generated it, at what time.

For a PR report, storage already retains its snapshot, prompt, model-call records,
and earlier generated versions. Successful reruns become current; failed reruns do
not displace the current report. Writes check the source snapshot and save the report
and its generation records together in a database transaction.

For aggregates, storage retains the same generation history plus links to the
exact input report versions. Suppose a monthly report used PR report version 1.
Regenerating that PR report creates version 2 but leaves the monthly report linked
to version 1. Requesting an updated monthly report uses the latest inputs and saves
a new result. Both results remain available for investigation and future comparison.
Nothing automatically regenerates reports higher in the tree.

Full payload retention, the default, keeps request and response text. The optional
`hashes_only` setting keeps hashes and metadata instead of those payloads; saved
sources, reports, and prompt files remain. Full retention gives more detail when
investigating an individual call. Cost reporting uses configured token prices and
is an estimate, not a provider invoice.

[ADR-0011](adr/0011-aggregate-report-provenance.md) defines the current input and version
rules. Database changes use new numbered migrations; applied migrations are never
rewritten. Legacy claim tables are historical structures, not the intended design
for aggregate storage.

## 7. Choosing AI models

A registry configures providers, model names, input/output limits, prices, and model
preferences for each generation stage. The router chooses the first eligible model
with enough estimated capacity. Switching to a supported model is a configuration
change. Supporting a new API protocol requires an adapter.

Only adapters import vendor SDKs. Generation uses a common provider interface and
records the chosen model and routing reason. Before each attempt, including a repair,
code estimates the system instructions, input text, response schema, and request
overhead, while reserving room for output. Oversized requests are rejected rather
than silently shortened. Estimates are approximate, so provider failures still need
handling.

The [example configuration](../config/examples/m1.yaml) is opt-in. Model quality
has not been established by merely adding a registry entry.

## 8. Running the service and handling feedback

The current application is a Python CLI with Postgres 15+; Docker Compose supplies
Postgres 16. See the [walkthrough](M1-WALKTHROUGH.md) for setup. A web service, workers,
sign-in, access control, and reader feedback are not implemented. Durable background
jobs and recovery from a process crash are also future work.

## 9. Evaluation

Automated tests check collection, report formatting, retry limits, provider failures,
and storage history. The checked-in demo uses a synthetic source and hand-authored
response. These checks exercise the software; usefulness and accuracy need human
review of real generated reports. The planned 20-PR study belongs to M3.

## 10. Open questions

Normal aggregate requests list the remote window and refresh all selected PRs before
looking for cached results. Unchanged sources reuse snapshots; changed sources need
new PR reports. `--local-only` explicitly uses saved snapshots and does not promise
remote completeness or freshness. GitHub does not provide a simultaneous read of an
entire repository, so edits during collection remain an operational limitation.

Later work includes report comparison and manual version selection, optional model
assessment, feedback, private access, operational retention settings, and the web
interface. The current decisions do not settle those product details.

## 11. M2 execution and storage

`aggregate owner/repo --since DATE --until DATE --altitude manager` resolves PRs and
uses their latest successful reports. Missing PR reports are generated through the
M1 service. Empty windows make no model calls. If a required PR report fails, the
aggregate stops rather than silently leaving that input out.

The engine uses one request when it fits. Otherwise it plans a stable tree and runs
it from the bottom up. Each actual request is routed using the configured models,
and its rendered input is checked before generation and any repair. Oversized
intermediate outputs stop the parent request if no configured model can accept them.

Each node's cache key includes its exact input versions and text, source hashes,
query, prompt, schema, and generation settings. The latest matching successful result
is reused. `--regenerate` bypasses aggregate caches throughout the tree; it preserves
earlier results and does not force regeneration of existing PR reports.

Migration 0005 adds `aggregate_reports`, `aggregate_report_inputs`, and
`aggregate_report_calls`. A report stores its versioned document and settings as JSON;
relational input edges enforce links to existing PR reports or child aggregates. Code
rechecks each supplied input against the saved version before writing. Report, input
edges, and model-call history are saved together in a transaction. The call writer is
shared with M1. No current report depends on legacy aggregate-claim tables.

Nodes are saved independently. A completed child or failed attempt remains inspectable
if a later call fails. Concurrent identical requests may both generate a result; both
versions are kept. This is synchronous execution, not a durable background job system.

`show-aggregate ID` shows the result and commands for its immediate inputs.
`show-report ID` opens an exact historical PR report. Both support `--verbose` for
generation details. The aggregate view lists all underlying GitHub PR links and their
code-computed count. It does not ask the model to choose links or calculate coverage.

The credential-free demo uses this same engine with an in-memory store; `--persist`
uses Postgres. Human sample review and milestone release integration remain separate
from the automated checks. See [release evidence](releases/m2.md).
