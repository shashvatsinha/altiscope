# Prompts

Prompts are versioned files. Each `llm_calls` row records the SHA-256 hash of the
prompt file used. Never edit a prompt that has produced published reviews; add
`vN+1.md`. The loader selects the highest version for each stage.

Each file has front matter (`stage`, `version`, `schema_version`) followed by the
system prompt. Code assembles the user input from the PR snapshot. Full retention
stores the assembled request; hashes-only retention keeps its hash.

Prompt design rules that apply to every stage:

- Describe work, never people. No evaluative language about individuals.
- Say less rather than guess. "Could not determine" is a valid and expected output.
- PR reviews are based on code changes and linked to their source PR by the application.
  No per-claim citations or assessments are required.
- Numbers come from computed facts, which are provided; do not invent or recompute them.
