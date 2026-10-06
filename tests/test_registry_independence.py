from altiscope.llm.registry import (
    accepted_returned_model_names,
    contradicting_returned_models,
    same_underlying_model,
)

IDENTITY = dict(
    registry_key="sonnet",
    wire_name="claude-sonnet",
    underlying_model_id="anthropic/claude-sonnet-5",
)


def test_accepted_names_include_alias_forms_casefolded():
    names = accepted_returned_model_names(**IDENTITY)
    assert {"sonnet", "claude-sonnet", "anthropic/claude-sonnet-5", "claude-sonnet-5"} <= names


def test_blank_and_foreign_returned_models_contradict():
    returned = ("Claude-Sonnet-5", " ", "other/model")
    assert contradicting_returned_models(returned, **IDENTITY) == (" ", "other/model")


def test_same_underlying_model_ignores_case():
    assert same_underlying_model("Vendor/Model", "vendor/model")
    assert not same_underlying_model("vendor/a", "vendor/b")
