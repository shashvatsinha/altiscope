# ADR-0011: Save report inputs and generation history

Status: accepted (owner decisions during the 2026-09-08 documentation review).

Corrects the M2 design on this branch following owner review. Replaces the
claim-link and coverage proposals in ADR-0004, ADR-0007, and ADR-0008. It keeps
ADR-0010's overall PR review and generation history.

## Why

A reader asks what changed in billing this month. Altiscope should summarize the
relevant PR reports. If the reader wants to investigate, they can open the input
reports, continue through any intermediate summaries, and reach the original GitHub
PRs. They can then inspect the code or speak to someone who worked on the change.

The application knows which reports it supplied. Asking the model to choose source
references adds an unreliable judgment to a relationship we can record directly.
A coverage percentage based on those choices raises questions without measuring
whether the summary is useful or accurate.

## Decision

The model writes a headline, narrative, and sections. It produces no source list,
per-sentence citations, or coverage score. Code records every supplied report version
and derives the complete underlying PR link list from those records.

Each report version must retain:

- Its generated text and generation time.
- The model/provider, exact prompt version and content, and generation settings.
- The model-call attempts and their outcomes, using the existing retention policy.
- For a PR report, the saved PR snapshot and metadata.
- For a combined report, the exact versions of all immediate input reports.

This history is provenance: it supports drill-down, troubleshooting, and comparison.
It does not promise that an LLM summary is factually correct.

## Versions and updates

Preserve successful earlier versions when generating another result. By default, a
new summary uses the latest successfully generated reports from the level below.
A failed attempt must not become the current report. Manual version selection is
future work.

Existing summaries retain their original inputs. Regenerating one PR report does
not rewrite an old monthly report or automatically trigger more calls. When someone
requests an update, resolve the latest inputs and create or reuse the appropriate
result. A cache match requires the same input versions and generation settings,
including prompt, schema, model, and reader level. Explicit regeneration must be
able to produce another attempt even with the same settings.

For example, a monthly report that used PR report 17 continues to link to 17 after
report 18 is generated for that PR. A requested update uses 18. Both monthly report
versions remain inspectable. Future comparison controls can use this retained history.

## Alternatives considered

- **Model-selected references and coverage:** rejected because source membership is
  already known by the application and citation presence does not measure accuracy.
- **Keep only the latest report:** rejected because it would erase the inputs and
  outputs needed to investigate an older summary or compare model and prompt changes.
- **Automatically regenerate dependent reports:** rejected to keep updates deliberate
  and avoid unrequested model calls.

## Implementation

Schema/prompt v4 removes model-selected references. The engine renders input reports
and records all their version identities and underlying PR links. The reference
validator, coverage calculator, and threshold setting have been removed. Historical
prompts and applied migrations remain unchanged.

M1 retains PR report reruns, source snapshots, and generation records. M2 now executes
summary trees, caches matching results, and saves aggregate versions and exact input
links using migration 0005. Both stages share the model-call writer. Before saving an
aggregate, storage checks its inputs against the specific saved report versions.
A failed node is retained and cannot displace a successful cached result.

Normal aggregate requests refresh GitHub sources; `--local-only` explicitly uses saved
data. The CLI supports `aggregate`, `show-aggregate`, and `show-report` for historical
PR reports. `--regenerate` bypasses aggregate caches and preserves previous results.
There is no automatic regeneration of reports above changed inputs.

Fresh-schema and populated-M1 upgrade tests cover the new migration. Full tree and
CLI regressions cover caching, input changes, failures, and drill-down. Human sample
review and release integration remain pending; see the [release evidence](../releases/m2.md).
