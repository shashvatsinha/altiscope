# Architecture

Altiscope would turn GitHub pull requests into accounts of engineering work for different
readers. A pull request brings together a proposed code change, its explanation, and
review discussion. This document explains how that material would become a report.
The [decision records](adr/) provide the engineering rationale.

## 1. Implementation status

The building blocks exist, but they are not yet connected into a working product.
The workflow described below is the intended design.

| Area | Today |
|---|---|
| Storage | Database design and a tool for applying it exist. |
| Preparing source material | Code for selecting files, calculating facts, and assembling AI input is tested. |
| Checking references and planning summaries | Implemented and tested as separate functions. |
| AI connections | Model selection and Anthropic/chat-completions connections exist. Tests do not yet establish real output quality. |
| Complete workflow | GitHub collection, saving results, second-model review, and report generation remain unbuilt. |
| Reader experience | Interface, sign-in, permissions, and feedback remain unbuilt. |
| Evaluation | No human-reviewed test collection or quality-comparison workflow yet. |

## 2. From source to report

The proposed flow is:

```text
Save a code change and its discussion
                 ↓
Calculate facts and prepare material
                 ↓
Ask AI for statements linked to evidence
                 ↓
Check references; request a second opinion
                 ↓
Combine statements for the reader's question
                 ↓
Show the account and supporting sources
```

For the [README's billing example](../README.md#what-it-would-look-like), separate changes
introduce background processing, retries, and duplicate-event checks. Altiscope would
first describe each change, then combine those descriptions into a manager's account.
The supporting statements would retain links to their original evidence.

There are three AI tasks: describe a change, review a statement, and combine statements.
Ordinary code handles source preparation, counts, reference checks, and storage.

## 3. Saving and preparing the source

Altiscope would periodically check GitHub and save copies of pull requests. Notifications
from GitHub could later speed up updates. An organization would connect through a GitHub
App; an individual could use a personal access token for evaluation.

The first version would summarize merged pull requests—changes accepted into the project.
Open and abandoned changes would contribute basic facts, such as counts and ages.
Changes made without a pull request would be outside the initial view.

Descriptions and comments can change after merge. Saving a separate version on each
refresh would preserve what a particular summary actually read. Fetching, saving, and
selecting the latest version still need implementation.

Existing preparation code filters files using rules for generated content, dependencies,
unavailable text, and size. It records why each file was excluded and tells the AI what
it has not read. These rules can exclude meaningful material and need evaluation.

Counts and timing are calculated in code. The intended interface would display these
facts directly from stored data, while the AI supplies descriptions. This does not
prevent an AI-written sentence from repeating a number incorrectly.

## 4. Claims and validation

A *claim* is one statement about a change, accompanied by references to supporting
material. References can identify files, sections of a change, quotations, comments,
or commits. The existing checks compare them with the saved material. They check
membership, not meaning; some matching rules also need tightening.

The proposed workflow asks the AI to repair invalid references once. If they remain
invalid, the result stays unpublished for review. That retry and storage workflow is
not implemented.

A second AI model would judge each claim as supported, partly supported, unsupported,
or impossible to determine, with an explanation. Its verdict would remain beside the
claim rather than replace it. The current proposal does not automatically withhold a
claim because the reviewer disagrees. Separate models can share mistakes, so the benefit
and cost of this review must be measured.

**A remaining gap:** headlines and paragraphs are generated alongside claims. There is
no check linking every sentence back to those claims. Removing an invalid claim can
leave its wording in the paragraph. The publication rules must address this before
reports reach readers. Existing warnings about evaluative language do not check accuracy.

## 5. Answering a reader's question

Readers would choose people, teams, or repositories, a date range, and a level of detail,
called *altitude*. Supported levels run from individual contributor to executive.
The design assigns changes to dates using merge time and to teams using membership at
that time. A future topic filter, such as reliability, is proposed.

Reports would be created when requested. If the source fits into one AI call, the system
can combine it directly. Otherwise, the existing planner divides it into ordered groups,
plans a summary of each group, and repeats until one report remains. Intermediate
summaries would be saved so readers could follow a statement through to the original
change. Larger reports would take longer and introduce more opportunities for distortion.

The source checker removes unrecognized references, drops claims with no valid source,
and fails if no claims survive. A remaining reference still needs to support the full
claim. Running these planned calls and saving their results remain unfinished.

An existing coverage calculation counts immediate inputs cited by a summary. At higher
levels those inputs may themselves be summaries, so the number does not establish how
much original work the final account represents. Its presentation remains undecided.

## 6. Keeping results traceable

Postgres stores sources, claims, and their relationships. Database checks ensure that
referenced records exist. Application checks must also ensure those sources belong to
the relevant change and are available to the reader.

The design retains older results when source material, AI instructions, or models change.
A report could be reused when its inputs and generation settings match, provided the
reader still has access. Reports are requested on demand rather than prepared on a fixed
weekly or quarterly schedule. Saving and reusing results still need implementation.

Records of AI calls would identify the model, instructions, usage, cost, and outcome.
Settings allow retaining full requests and responses or only their identifying hashes.
Full retention helps investigation but duplicates source code; storage behavior and the
organizational default remain to be settled.

For implementation details, see the [database definition](../migrations/0001_initial.sql)
and [provenance decision](adr/0004-provenance-as-rows.md). AI instructions are versioned
files under `prompts/`; published versions should be preserved.

## 7. Choosing AI models

The [model configuration](../config/models.yaml) specifies available models and an ordered
preference for each task. The selection code chooses the first eligible model with room
for the estimated input. It can avoid the producing model or connection when selecting
a reviewer, although that does not guarantee independent judgment.

The current connections support Anthropic and compatible chat-completions services,
including suitable internal services. Compatibility depends on the particular service
and its settings. Input-size estimates can be wrong; the complete workflow must handle
that. Model selection follows configured preference and capacity, not automatic cost
optimization. Defaults have not been established through quality evaluations.

## 8. Running the service and handling feedback

The proposed deployment has a web service, a background worker, and Postgres. The worker
would handle collection and AI tasks, including retries. The web service would provide
reports, evidence exploration, and feedback. Neither service exists yet; the current
command-line tool supports database setup and inspection of model and prompt settings.

Readers should see only information from repositories they can access. That restriction
must apply when selecting inputs, reopening saved reports, and exploring evidence.
Sign-in, access checks, and records of reader actions remain unbuilt.

GitHub and configured AI services are the intended external connections. An internal
model can keep AI processing within the organization's network; actual network
restrictions require deployment controls.

The feedback design lets readers flag a statement or report and explain the problem.
Flags would also appear on reports built from disputed statements. Human corrections
would become test cases for future changes. The tables exist; this workflow does not.
The product describes work and excludes employee ranking or evaluation.

## 9. The next milestone

The [roadmap](ROADMAP.md#1-vertical-slice-on-one-repository-no-ui) starts with one repository:
collect its changes, produce and check claims, save evidence and reviewer verdicts, and
inspect the results through a command-line tool. The
[thesis](../THESIS.md#how-to-test-the-thesis) defines what to measure.

Priority failures are unsupported interpretations, prose that contradicts checked claims,
inputs too large to process, and regressions after model or instruction changes. Access
controls must be tested before serving readers. Existing component tests establish
neither report quality nor a working product.

## 10. Open questions

1. **Changing work:** when should open or abandoned changes receive descriptions?
2. **Comparisons:** what should side-by-side accounts of different people's work show?
3. **Retention:** how much AI request and response content should organizations keep?
4. **Interface:** how should readers move from an account to its evidence?
5. **Review:** when does a second model help enough to justify its cost, and how should
   disagreement affect publication?
6. **Coverage:** does the existing citation statistic help readers, and how should it appear?
7. **Prose:** how should every published paragraph be reconciled with its checked claims?

Search over embedded content, separate commit summaries, scheduled reports, and automated
code-quality, security, or compliance analysis remain outside the first version.
