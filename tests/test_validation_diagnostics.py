from __future__ import annotations

import os
from unittest.mock import Mock

import psycopg
import pytest
from pydantic import ValidationError

from altiscope.aggregate.generate import generate_aggregate
from altiscope.aggregate.inputs import render_inputs
from altiscope.aggregate.planner import estimate_aggregate_request_tokens
from altiscope.ingest.snapshot import PullRequestSnapshot
from altiscope.llm.provider import GenerationResult, Provider, Usage
from altiscope.llm.router import route
from altiscope.llm.types import Stage
from altiscope.llm.validation import sanitize_diagnostic, validation_diagnostic
from altiscope.prompts import latest_prompt
from altiscope.schemas.aggregate import AggregateOutput
from altiscope.schemas.pr_summary import PrReviewOutput
from altiscope.store.calls import save_calls
from altiscope.summarize.context import render_user_prompt
from altiscope.summarize.fixture import FixtureProvider, fixture_registry
from altiscope.summarize.generate import GeneratedAccount, generate_account, request_tokens
from altiscope.summarize.service import prepare
from tests.conftest import REPO_ROOT
from tests.test_aggregate_generation import INPUTS


def run(stage: Stage, snapshot: PullRequestSnapshot, provider: Provider, budget: int = 100000):
    model = fixture_registry().models["fixture"]
    if stage == "pr_summary":
        return generate_account(
            prepare(snapshot),
            provider,
            model,
            system="instructions",
            max_tokens=1000,
            effort="low",
            input_budget=budget,
        )
    return generate_aggregate(
        provider,
        model,
        user="Summarize",
        inputs=INPUTS,
        system="instructions",
        max_tokens=1000,
        effort="low",
        input_budget=budget,
    )


@pytest.mark.parametrize("stage", ["pr_summary", "aggregate"])
@pytest.mark.parametrize("kind", ["missing", "extra_forbidden", "string_type"])
def test_diagnostic_reaches_repair_and_attempt(
    stage: Stage, kind: str, snapshot: PullRequestSnapshot
):
    import json

    field = "review" if stage == "pr_summary" else "headline"
    bad = {} if kind == "missing" else {field: 12 if kind == "string_type" else "ok"}
    if kind == "extra_forbidden":
        bad["sk-secret\nTraceback"] = "Bearer confidential"
    provider = FixtureProvider([json.dumps(bad)] * 3)
    generated = run(stage, snapshot, provider)
    assert provider.calls == 2
    diagnostic = generated.attempts[0].errors[1]
    assert f"{'extra' if kind == 'extra_forbidden' else field}: {kind}" in diagnostic
    assert diagnostic in generated.attempts[1].user
    assert "secret" not in diagnostic and "confidential" not in diagnostic


@pytest.mark.parametrize("stage", ["pr_summary", "aggregate"])
@pytest.mark.parametrize("reason", ["refusal", "max_tokens", "transport_error", "unknown", "other"])
def test_terminal_diagnostic_never_triggers_repair(
    stage: Stage, reason: str, snapshot: PullRequestSnapshot
):
    provider = Mock()
    provider.generate_structured.return_value = GenerationResult(
        parsed=None,
        raw_text="",
        model_id="fixture",
        stop_reason=reason,
        usage=Usage(0, 0),
        latency_ms=0,
        output_mode="native",
        validation_error="Authorization: Bearer secret\nTraceback",
    )
    generated = run(stage, snapshot, provider)
    assert provider.generate_structured.call_count == 1
    assert generated.attempts[0].errors == (reason,)


@pytest.mark.parametrize("stage", ["pr_summary", "aggregate"])
def test_diagnostic_repair_budget(stage: Stage, snapshot: PullRequestSnapshot):
    if stage == "pr_summary":
        budget = request_tokens("instructions", render_user_prompt(prepare(snapshot)))
    else:
        budget = estimate_aggregate_request_tokens(
            "instructions", render_inputs("Summarize", INPUTS)
        )
    provider = FixtureProvider(["{}"])
    generated = run(stage, snapshot, provider, budget)
    assert provider.calls == 1 and len(generated.attempts) == 1
    assert "missing" in generated.attempts[0].errors[1]
    errors = (
        generated.publication.errors
        if isinstance(generated, GeneratedAccount)
        else generated.errors
    )
    assert "oversized_input" in errors[0]


def test_diagnostics_are_bounded_and_exclude_untrusted_error_parts():
    import json

    payload = {"headline": "ok", "narrative": "ok", "sections": [{"heading": 42}] * 100}
    with pytest.raises(ValidationError) as caught:
        AggregateOutput.model_validate_json(json.dumps(payload))
    diagnostic = validation_diagnostic(caught.value, AggregateOutput)
    assert len(diagnostic) <= 512 and diagnostic.endswith("; ...")
    assert diagnostic.count(": ") == 8
    assert "heading: string_type" in diagnostic and "text: missing" in diagnostic
    for unsafe in ["sk-secret" * 1000, "review: missing\nTraceback secret", "secret: missing"]:
        assert sanitize_diagnostic(unsafe, PrReviewOutput) == "output: schema_validation_failed"
    assert sanitize_diagnostic("review: missing; " * 100, PrReviewOutput).endswith("; ...")


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("ALTISCOPE_DATABASE_URL"), reason="needs Postgres")
@pytest.mark.parametrize("stage", ["pr_summary", "aggregate"])
@pytest.mark.parametrize("retention", ["full", "hashes_only"])
def test_saved_diagnostics_and_payload_retention(
    database: str, snapshot: PullRequestSnapshot, stage: Stage, retention: str
):
    registry = fixture_registry()
    generated = run(stage, snapshot, FixtureProvider(["{}", "{}"]))
    with psycopg.connect(database) as conn:
        _, ids = save_calls(
            conn,
            attempts=generated.attempts,
            output_type=PrReviewOutput if stage == "pr_summary" else AggregateOutput,
            prompt=latest_prompt(REPO_ROOT / "prompts", stage),
            decision=route(registry, stage, 1000),
            registry=registry,
            retention=retention,
        )
        rows = conn.execute(
            "SELECT error,request_payload,response_text,request_hash,response_hash "
            "FROM llm_calls WHERE id = ANY(%s) ORDER BY attempt_ordinal",
            (list(ids),),
        ).fetchall()
        assert len(rows) == 2
        for row, attempt in zip(rows, generated.attempts, strict=True):
            assert row[0] == "; ".join(attempt.errors) and "missing" in row[0]
            assert len(row[3]) == len(row[4]) == 64
            if retention == "full":
                assert row[1]["user"] == attempt.user and row[2] == "{}"
            else:
                assert row[1] is None and row[2] is None
        conn.rollback()
