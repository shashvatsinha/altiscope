# One change, explained

[Read the complete account with evidence and omissions](sample.txt).

> run() acquires a module-level lock.
>
> A test for run() was added.

This is a **synthetic fixture with a hand-authored recorded response**, not output from
a live model or a real acme/widgets PR. Run `uv run altiscope demo` to reproduce it
without credentials, Docker, or model calls. The same context preparation, provider
protocol, generation, citation validation and renderer power the live workflow.
Use `uv run altiscope demo --persist` to also exercise Postgres snapshot and account storage.

## Review of the sample

Agent review, 2026-09-07; owner/human review is still pending.

- The first claim is supported by the added module-level lock and `with _lock` block.
  Its commit reference describes adding the lock, and its description quote matches.
- The second claim is supported by the added test file and conversation comment.
  It does not claim the test proves thread safety.
- Additions/deletions include the excluded lockfile. File totals match the fixture.
- The lockfile's 780 changed lines are explicitly excluded. No claim describes its contents.
- No reduction in incidents, performance improvement, or judgment about people is asserted.

Citation checks establish membership, not semantic truth. The account remains explicitly
unverified. This small fixture and failure regression set do not establish real-world
model quality; the human-reviewed evaluation belongs to milestone 3.
