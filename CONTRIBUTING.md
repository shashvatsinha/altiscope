# Contributing

Thank you for considering it. A few things that matter more here than in most projects.

## Accuracy is the product

Any change that touches what the model sees, what it is asked, or how its output is
validated needs to answer: can this cause a summary to state something the source does
not support, or to leave out work it should mention? If the answer is not "no", it needs
a test against the golden set (once it exists) or a written argument in the PR.

## Decisions live in ADRs

`docs/adr/` records the reasoning behind the architecture. To change a decision, add a
new ADR that supersedes the old one and link both. Do not edit the reasoning of an
accepted ADR.

## Prompts are versioned

Never edit a prompt file that has produced published summaries. Add a new version file
and switch the default in code. The content hash is recorded on every LLM call, and
changing a file in place would make old rows unreproducible.

## Schema changes

Add a new numbered migration. Never edit an applied one. Keep the provenance invariants:
claims have evidence rows, aggregate claims have source rows, polymorphic references use
nullable FKs with a `CHECK`.

## Development

```bash
uv sync --extra dev
docker compose up -d db
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

Pull requests should be small and describe the "why". Commit messages in the imperative.
