# M2 walkthrough: Understand a repository over time

M2 combines saved PR reports into a summary for an engineer, manager, or executive.
Every result retains the exact reports it read, its model and prompt details, and links
to all underlying GitHub PRs. Regeneration keeps earlier versions.

Run these commands from the repository root. The CLI reads prompts, configuration,
and demo fixtures relative to that directory.

## 1. Try the credential-free example

```bash
uv sync --extra dev --frozen
uv run altiscope demo --stage aggregate --altitude ic
uv run altiscope demo --stage aggregate --altitude manager
uv run altiscope demo --stage aggregate --altitude exec
```

The example has four synthetic billing PRs: retry temporary failures, deduplicate
incoming events, record failed jobs, and test the retry and duplicate paths. Compare
[engineer](../examples/m2/sample-ic.txt) and [manager](../examples/m2/sample-manager.txt)
reports to see how the level of detail changes.

Responses are hand-authored recordings, not live model output. The fictional GitHub
URLs demonstrate link formatting; they do not point to real PRs.

Each run executes the actual aggregate service and then repeats the request. The first
request makes one fixture call; the repeat uses the cache with zero calls.

## 2. Exercise multiple levels

```bash
uv run altiscope demo --stage aggregate --altitude manager --multi-level
```

This gives the demo model a deliberately small input budget. The service generates
two group reports and then a final report: three calls in total. A repeated request
reuses all three. All four original PR links remain available regardless of which
changes the generated prose mentions. See the [sample](../examples/m2/sample-multilevel.txt).

## 3. Save the example and follow its inputs

Start a development Postgres database and apply all migrations:

```bash
docker compose up -d db
uv run altiscope db migrate
uv run altiscope demo --stage aggregate --altitude manager --multi-level --persist
```

Each migration and its version record commit together. For historical marker failures, use the
[bounded recovery procedure](MIGRATIONS.md).

The default connection is `postgresql://altiscope:altiscope@localhost:5432/altiscope`.
Use `ALTISCOPE_DATABASE_URL` to select a different development database.

The demo prints a command with the saved report ID:

```text
altiscope show-aggregate REPORT_ID --verbose
```

Run it with the actual ID. Normal output shows the summary and all underlying PR
links. It also prints commands for the exact intermediate reports it used. Open one
of those, then follow its `show-report` commands to individual PR reports:

```text
altiscope show-aggregate CHILD_REPORT_ID
altiscope show-report PR_REPORT_ID --verbose
```

`show-report` loads that historical version, including its source URL and author.
It does not switch to the latest PR report. Verbose output includes saved facts,
input exclusions, and the exact prompt. For aggregates, verbose output includes
model settings, timestamps, prompt text, and model-call outcomes.

Repeating the persisted demo deliberately generates another aggregate version, then
checks a cache hit. Earlier aggregate versions remain available by ID. Synthetic
PR reports are reused when already saved.

## 4. Summarize a real repository

Configure a model provider before using live generation. The existing
[model examples](../config/examples/) work for the aggregate stage as well as PR
reports. For example, `config/examples/m1.yaml` is an existing OpenRouter setup;
set its expected `OPENROUTER_API_KEY` in your environment and choose it:

```bash
export ALTISCOPE_MODELS_CONFIG=config/examples/m1.yaml
uv run altiscope aggregate owner/repository \
  --since 2026-06-01 --until 2026-06-30 --altitude manager
```

The configured model must support the declared protocol and capacity. These settings
are user configuration, not a recommendation or a claim of measured model quality.
A GitHub token is optional for public repositories; set `ALTISCOPE_GITHUB_TOKEN` to
use one and obtain the corresponding rate limits. Live commands can incur model charges.

Both dates are inclusive UTC calendar dates. The command lists merged PRs from GitHub
and refreshes every selected source, detecting changes in descriptions, patches, or
discussion. It reuses each unchanged snapshot and its latest successful PR report.
A missing report is generated using the M1 service. A changed snapshot needs a report
for that new source version.

Once inputs are resolved, the command generates or reuses the aggregate and prints
its ID. Repeating an unchanged request still checks GitHub but makes no model calls
when all required reports are cached. A failed PR report stops the request instead
of silently leaving that PR out.

For an explicit offline view of already saved sources:

```bash
uv run altiscope aggregate owner/repository \
  --since 2026-06-01 --until 2026-06-30 --altitude manager --local-only
```

This skips GitHub, so the saved window may be incomplete or stale. It may still make
model calls for missing PR reports or aggregates. If the resolved window is empty,
the command prints `0 PRs merged` and makes no model calls.

Repository names are case-insensitive. A remote request resolves the current name from
GitHub's stable repository ID. A rename preserves saved reports and cache reuse.
After a remote refresh, use the current name for `--local-only` requests.
See [repository identity rules](REPOSITORY-IDENTITY.md) for name reuse and conflict behavior.

If output has an invalid format, the service permits one repair request.
Saved call errors contain bounded schema diagnostics, without response values or SDK exception details.
A failed repair preserves earlier usable reports. Verbose inspection shows the call outcomes.

## 5. Try another prompt or model

Prompts are versioned files. Add a new prompt version with the current response
schema rather than editing a prompt that has produced saved output. Change model
selection in the registry when trying another configured model.

To regenerate a PR report, use the existing `summarize owner/repository NUMBER`
command after any desired source refresh. The next aggregate request uses that
latest successful PR report. To request a fresh aggregate even when the same settings
and inputs already have a cached result:

```bash
uv run altiscope aggregate owner/repository \
  --since 2026-06-01 --until 2026-06-30 --altitude manager --regenerate
```

This bypasses aggregate caches throughout the tree. It does not force regeneration
of existing PR reports. All prior report versions remain inspectable. No report
higher in the tree is automatically updated when an input changes.

Manual input-version selection and a comparison interface are future work. You can
already inspect older reports by ID and compare their text and generation details.

## 6. Validate the implementation

With development Postgres running:

```bash
ALTISCOPE_DATABASE_URL='postgresql://altiscope:altiscope@localhost:5432/altiscope' \
  uv run pytest -o addopts='' -q
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Without `ALTISCOPE_DATABASE_URL`, database tests are skipped. Integration tests write
synthetic data; use a development/test database. Migration upgrade tests additionally
create isolated schemas and remove them afterward.

The [release evidence](releases/m2.md) records validation and remaining release steps.
There is no coverage percentage or model-selected source list. Input records support
investigation; real report quality still needs evaluation on real engineering work.
