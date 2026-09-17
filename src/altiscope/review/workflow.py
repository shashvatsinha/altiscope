"""Application services for starting, revealing, and resuming guided reviews."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import psycopg

from altiscope.assessment.status import assessment_observation_state
from altiscope.store.evaluation import save_evaluation_artifact

__all__ = ["EvaluationArtifacts", "assessment_observation_state", "retain_protocol_artifacts"]


@dataclass(frozen=True)
class EvaluationArtifacts:
    protocol_id: UUID
    dataset_id: UUID
    record_contract_id: UUID


def retain_protocol_artifacts(
    conn: psycopg.Connection, *, evaluation_dir: Path
) -> EvaluationArtifacts:
    """Retain the exact checked-in protocol, dataset, and record-contract content."""
    protocol_text = (evaluation_dir / "m3-protocol-v1.md").read_text()
    dataset_text = (evaluation_dir / "m3-eval-set-v1.md").read_text()
    contract_text = (evaluation_dir / "m3-review-record-v1.example.json").read_text()
    contract_example = json.loads(contract_text)
    if not isinstance(contract_example, dict):
        raise ValueError("review record contract example must be a JSON object")
    protocol_id = save_evaluation_artifact(
        conn,
        kind="protocol",
        external_id="m3-evaluation-v1",
        version="v1",
        content={"media_type": "text/markdown", "text": protocol_text},
    )
    dataset_id = save_evaluation_artifact(
        conn,
        kind="dataset",
        external_id="m3-markitdown-20-v1",
        version="v1",
        content={"media_type": "text/markdown", "text": dataset_text},
    )
    contract_id = save_evaluation_artifact(
        conn,
        kind="record_contract",
        external_id="m3-review-record-v1",
        version="v1",
        content={"media_type": "application/json", "example": contract_example},
    )
    return EvaluationArtifacts(protocol_id, dataset_id, contract_id)
