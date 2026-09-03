# Prompts

Prompts are versioned files. The runtime records the sha256 of the file it used on every
`llm_calls` row, so any summary can be reproduced and any prompt change is visible in the
data. Never edit a prompt file in place once it has produced published summaries; add
`vN+1.md` and switch the default in code.

Each file has a small front matter block (`stage`, `version`, `schema_version`) followed
by the system prompt. The user turn is assembled by code from the PR snapshot and is not
part of the versioned prompt, but its template lives next to the code that builds it and
is covered by the same hash rule.

Prompt design rules that apply to every stage:

- Describe work, never people. No evaluative language about individuals.
- Say less rather than guess. "Could not determine" is a valid and expected output.
- Every claim needs evidence the system can check against the snapshot.
- Numbers come from computed facts, which are provided; do not invent or recompute them.
