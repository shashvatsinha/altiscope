# M3 workflow example

Run [`synthetic_study.py`](synthetic_study.py) after the database setup in the
[M3 walkthrough](../../docs/M3-WALKTHROUGH.md). It saves one synthetic PR
comparison and one manager aggregate comparison. Each contains two generation
recipes and their prompt-only baselines. Every response below is **hand-authored**;
the script makes no live model call.

The synthetic PR changes `run()` to acquire a lock and adds a test that calls
the function once. One candidate fixture says:

> The change makes run() thread-safe and a test proves concurrent safety.

The saved patch supports the lock, but the supplied test does not exercise
concurrent callers. A separate fixture assessor returns `disagree` with the
rationale that the test calls `run()` once. The script persists an initial
`incorrect` revision, a guided assessment exposure, and a post-assessment
observation under the ID `synthetic-reviewer-fixture`. This is a simulated
review record for workflow testing, not a human correctness judgment or an
assessment detection result.

The aggregate fixture is a `single_step` manager composition of one exact
saved synthetic PR report. Its response summarizes the lock and test, while
the application supplies the exact input report version and PR link. The
`show-comparison` command displays that navigation and separately labels
generation and assessment costs. Fixture providers report no priced usage, so
cost appears as unavailable rather than a claimed zero-dollar real result.

The optional `--pilot-pr19` mode uses a selected real development PR snapshot
with hand-authored responses, including a deliberately unsupported HTML
charset-detection assertion. It tests the same save/inspect/reveal/export
path. It is not evidence of live model quality or qualified MarkItDown review.

The owner-requested live 20-PR run and later owner workflow inspection are
tracked in the [execution plan](../../docs/evaluation/m3-workflow-plan.md).
