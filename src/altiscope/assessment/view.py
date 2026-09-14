"""Reveal-safe assessment rendering for CLI and future human-review workflows."""

from __future__ import annotations

from altiscope.store.comparisons import StoredAssessment


def render_assessment(assessment: StoredAssessment | None, *, reveal: bool = False) -> str:
    """Render nothing for not-run and hide completed model output unless explicitly revealed."""
    if assessment is None:
        return ""
    if assessment.verdict is not None and not reveal:
        return (
            f"Assessment {assessment.id}: completed; "
            "verdict and rationale hidden until explicitly revealed.\n"
        )
    heading = f"Assessment {assessment.id}: {assessment.status}"
    if assessment.verdict is not None:
        return heading + f"; verdict {assessment.verdict}\n{assessment.rationale}\n"
    if assessment.error_code is not None:
        detail = f": {assessment.error_message}" if assessment.error_message else ""
        return heading + f"; error {assessment.error_code}{detail}\n"
    return heading + "\n"
