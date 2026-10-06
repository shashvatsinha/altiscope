from __future__ import annotations

import pytest
from pydantic import ValidationError

from altiscope.assessment import render_assessment
from altiscope.schemas.verify import AssessmentOutput, AssessmentVerdict
from altiscope.store.recipes import registered_schema


def test_whole_result_assessment_schema_has_only_verdict_and_rationale():
    output = AssessmentOutput(
        verdict=AssessmentVerdict.agree,
        rationale="The complete result matches the supplied saved material.",
    )
    assert output.model_dump(mode="json") == {
        "verdict": "agree",
        "rationale": "The complete result matches the supplied saved material.",
    }
    with pytest.raises(ValidationError):
        AssessmentOutput.model_validate(
            {
                "verdict": "disagree",
                "rationale": "One item is wrong.",
                "claims": [{"verdict": "unsupported"}],
            }
        )


@pytest.mark.parametrize("verdict", ["agree", "disagree", "inconclusive"])
def test_whole_result_assessment_accepts_only_defined_verdicts(verdict: str):
    assert AssessmentOutput.model_validate({"verdict": verdict, "rationale": "Because."})


def test_no_assessment_preserves_normal_rendering():
    assert render_assessment(None) == ""


def test_only_whole_result_verify_schema_is_executable():
    with pytest.raises(ValueError, match="unsupported output schema"):
        registered_schema("verify", 1)
    registered = registered_schema("verify", 2)
    assert registered.contract_id == "altiscope.whole_result_assessment"
    assert registered.output_type is AssessmentOutput
