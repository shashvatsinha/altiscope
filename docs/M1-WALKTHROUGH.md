# Milestone 1 walkthrough

Run commands from the repository root. Requires Python 3.11+, uv, and Docker Desktop
for persisted workflows. Postgres 15+ may be supplied through `ALTISCOPE_DATABASE_URL`.

```bash
git clone https://github.com/shashvatsinha/altiscope.git
cd altiscope
# Until release, check out the milestone implementation branch.
uv sync --extra dev --frozen
uv run altiscope demo
```

The [checked-in sample](../examples/m1/README.md) is a synthetic source and hand-authored
response, replayed through the normal generation/validation/rendering services.
It makes no model call and needs no credentials. It is not a quality benchmark.

## Persisted fixture workflow

```bash
docker compose up -d db
uv run altiscope db migrate
uv run altiscope demo --persist
uv run altiscope show acme/widgets 42
# The default is concise. Add --verbose for PR provenance, facts, and omissions.
uv run altiscope show --verbose acme/widgets 42
```

The persisted demo uses the same snapshot and relational account storage as live input,
with an explicitly recorded fixture provider. Repeating it preserves the source version,
records another generation run, and selects one current account.

## Selected public PR

The live source selected for M1 is [Altiscope PR #2](https://github.com/shashvatsinha/altiscope/pull/2).
Supply a GitHub PAT through `ALTISCOPE_GITHUB_TOKEN` in the environment or local `.env`;
do not put tokens in command arguments or commit `.env`. Anonymous public reads also work
with GitHub's lower rate limit. M1 rejects private repositories.

```bash
uv run altiscope ingest shashvatsinha/altiscope 2
```

Files, commits, reviews and both comment collections paginate fully. A count mismatch,
changed PR during collection or exhausted retry budget fails ingestion without saving
partial source. Missing patches remain visible as exclusions. Repeating unchanged
collection reuses the source version; edits create an immutable new snapshot.

For an opt-in live model smoke, configure `OPENROUTER_API_KEY` in `.env`, then:

```bash
export ALTISCOPE_MODELS_CONFIG=config/examples/m1.yaml
uv run altiscope summarize shashvatsinha/altiscope 2
uv run altiscope show shashvatsinha/altiscope 2
```

This sends the selected public PR to OpenRouter and incurs its API cost. The M1 example
uses Claude Sonnet through OpenRouter's OpenAI-compatible endpoint. The registry remains
replaceable; this choice is not an evaluated model ranking.

The report shows an overall code-based review and its source PR link. `published`
means usable output, not verified interpretation. Malformed or empty output is repaired
at most once; terminal failure is `needs_review`. A failed run does not replace an
existing published review for the same snapshot. Use `show --verbose` for stored
snapshot/model provenance, facts and input omissions. No claim citations are required.

## Direct Anthropic API

Set `ANTHROPIC_API_KEY` in `.env` or the environment, then select the direct configuration:

```bash
export ALTISCOPE_MODELS_CONFIG=config/examples/anthropic.yaml
uv run altiscope summarize shashvatsinha/altiscope 2
uv run altiscope show --verbose shashvatsinha/altiscope 2
```

This uses the Anthropic SDK and API directly. The progress indicator and stored
provenance show provider `anthropic` and model `claude-sonnet-5`. The example's model
limits and prices follow [Anthropic's documentation](https://platform.claude.com/docs/en/models/sonnet-5/whats-new-sonnet-5).
The default registry also includes `anthropic-sonnet`; add it to a stage's candidates
to select it in a custom configuration. OpenRouter remains the default route.

## OpenRouter

Your `OPENROUTER_API_KEY` can select any configured model family. Set the configuration
file before running `summarize`:

```bash
export ALTISCOPE_MODELS_CONFIG=config/examples/openrouter-anthropic.yaml
uv run altiscope summarize shashvatsinha/altiscope 2

export ALTISCOPE_MODELS_CONFIG=config/examples/openrouter-openai.yaml
uv run altiscope summarize shashvatsinha/altiscope 2
```

Both configurations use OpenRouter's OpenAI-compatible endpoint and JSON Schema output.
The Anthropic example uses `anthropic/claude-sonnet-5`; the OpenAI example uses
`openai/gpt-5.5`. OpenRouter's model catalog and structured-output support can change;
replace the model ID and limits in the example if your account exposes a different model.
The key is read from `.env` and never included in request provenance.
New source versions never silently reuse an older source's account.

Set `ALTISCOPE_LLM_PAYLOAD_RETENTION=hashes_only` to retain request/response hashes rather
than duplicate full LLM payloads. Source snapshots and published reviews are still retained.
Usage, selected configuration and available provider metadata remain recorded.

## Validation

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
ALTISCOPE_DATABASE_URL=postgresql://altiscope:altiscope@localhost:5432/altiscope uv run pytest
uv run altiscope db migrate
```

Tests use fake providers and fake HTTP; no paid credentials are needed. Database tests
exercise rollback, concurrent latest selection, compound comment identities, publication,
repair, failed runs and retained historical output. Use a development/test database.

## Limitations

PR provenance is not semantic verification. Prompts cannot guarantee absence of
unsupported interpretation or an incorrectly repeated number. Token estimates include schema and request overhead but are not exact.
Collection can miss edits that GitHub does not expose through its PR update timestamp;
M1 does not provide a cross-endpoint transactional GitHub snapshot. Excluded patches can
contain important work. No employee evaluation, UI, private ingestion, aggregation,
background sync, or mandatory second-model review is included.
