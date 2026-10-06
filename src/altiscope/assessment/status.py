"""Shared mapping from persisted assessment statuses to review observation states."""


def assessment_observation_state(status: str) -> str:
    """Map persisted execution outcomes to the protocol's observation availability states."""
    if status in ("succeeded", "inconclusive"):
        return status
    if status in ("preflight_failed", "invalid_output", "refused", "failed"):
        return "failed"
    raise ValueError(f"unsupported persisted assessment status: {status}")
