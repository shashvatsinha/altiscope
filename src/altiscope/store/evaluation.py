"""Append-only human-evaluation records and assessment exposure history."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

ArtifactKind = Literal["protocol", "dataset", "record_contract"]
UsefulnessStatus = Literal["measured", "unavailable", "not_applicable"]
EffortComponent = Literal["preparation", "reading", "checking", "correction", "assessment_related"]


def _hash_json(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class EffortMeasure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component: EffortComponent
    unit: Literal["milliseconds"] = "milliseconds"
    status: Literal["measured", "not_applicable", "unavailable"]
    value: int | None = Field(default=None, ge=0)
    method: Literal["timer", "estimated"] | None = None
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def _validate_measure(self) -> EffortMeasure:
        if self.status == "measured":
            if self.value is None or self.method is None or self.unavailable_reason is not None:
                raise ValueError("measured effort requires value/method and no unavailable reason")
        elif self.value is not None or self.method is not None:
            raise ValueError("unmeasured effort must not contain a value or method")
        elif self.status == "unavailable" and not self.unavailable_reason:
            raise ValueError("unavailable effort requires a reason")
        elif self.status == "not_applicable" and self.unavailable_reason is not None:
            raise ValueError("not-applicable effort must not contain an unavailable reason")
        return self


class ReviewRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["initial_blind", "post_assessment", "adjudication"]
    blind_status: Literal["confirmed_unexposed", "known_exposed", "unknown"]
    correctness_label: Literal["correct", "incorrect", "unclear"] | None = None
    correctness_rationale: str | None = None
    correction: str | None = None
    usefulness_status: UsefulnessStatus
    usefulness_score: int | None = Field(default=None, ge=1, le=5)
    usefulness_rationale: str | None = None
    effort: tuple[EffortMeasure, ...]
    created_at: datetime

    @model_validator(mode="after")
    def _validate_revision(self) -> ReviewRevisionInput:
        if self.usefulness_status == "measured":
            if self.usefulness_score is None or not self.usefulness_rationale:
                raise ValueError("measured usefulness requires a score and rationale")
        elif self.usefulness_score is not None:
            raise ValueError("unmeasured usefulness must not have a score")
        components = [measure.component for measure in self.effort]
        if len(components) != len(set(components)):
            raise ValueError("a revision cannot repeat an effort component")
        return self


@dataclass(frozen=True)
class ReviewSession:
    id: UUID
    result_id: UUID
    source_id: UUID
    reviewer_id: str


def save_evaluation_artifact(
    conn: psycopg.Connection,
    *,
    kind: ArtifactKind,
    external_id: str,
    version: str,
    content: dict[str, object],
) -> UUID:
    """Content-address and retain a protocol, dataset, or record contract."""
    if not external_id.strip() or not version.strip():
        raise ValueError("evaluation artifact identity must not be blank")
    digest = _hash_json(content)
    artifact_id = uuid4()
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO evaluation_artifacts(id,kind,external_id,version,content,content_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(kind,external_id,version) DO NOTHING RETURNING id",
            (artifact_id, kind, external_id, version, Jsonb(content), digest),
        ).fetchone()
        if row is not None:
            return UUID(str(row[0]))
        existing = conn.execute(
            "SELECT id,content_hash FROM evaluation_artifacts "
            "WHERE kind=%s AND external_id=%s AND version=%s",
            (kind, external_id, version),
        ).fetchone()
        if existing is None or existing[1] != digest:
            raise ValueError("evaluation artifact version already has different content")
        return UUID(str(existing[0]))


def _require_artifact_kind(
    conn: psycopg.Connection, artifact_id: UUID | None, expected: ArtifactKind
) -> None:
    if artifact_id is None:
        return
    row = conn.execute(
        "SELECT kind FROM evaluation_artifacts WHERE id=%s", (artifact_id,)
    ).fetchone()
    if row is None or row[0] != expected:
        raise ValueError(f"expected a {expected} evaluation artifact")


def create_review_session(
    conn: psycopg.Connection,
    *,
    result_id: UUID,
    reviewer_id: str,
    protocol_artifact_id: UUID,
    record_contract_artifact_id: UUID,
    case_id: str,
    case_kind: Literal["pr", "aggregate"],
    case_group: Literal["development", "held_out"],
    reader_role: Literal["ic", "manager", "exec"],
    familiarity_level: Literal["direct", "repository", "domain", "prepared", "none"],
    familiarity_basis: str,
    declared_prior_exposure: Literal["none_declared", "known", "unknown"],
    result_presentation_ordinal: int,
    started_at: datetime,
    invocation_id: UUID | None = None,
    dataset_artifact_id: UUID | None = None,
) -> ReviewSession:
    if not reviewer_id.strip() or not case_id.strip() or not familiarity_basis.strip():
        raise ValueError("review identity and familiarity basis must not be blank")
    if result_presentation_ordinal <= 0:
        raise ValueError("result presentation ordinal must be positive")
    session_id = uuid4()
    with conn.transaction():
        result = conn.execute(
            "SELECT source_id,status FROM comparison_run_results WHERE id=%s", (result_id,)
        ).fetchone()
        if result is None or result[1] != "succeeded":
            raise ValueError("human review requires a successful exact result")
        _require_artifact_kind(conn, protocol_artifact_id, "protocol")
        _require_artifact_kind(conn, dataset_artifact_id, "dataset")
        _require_artifact_kind(conn, record_contract_artifact_id, "record_contract")
        if invocation_id is not None:
            member = conn.execute(
                "SELECT 1 FROM comparison_members WHERE invocation_id=%s AND result_id=%s",
                (invocation_id, result_id),
            ).fetchone()
            if member is None:
                raise ValueError("review invocation did not present the exact result")
        conn.execute(
            "INSERT INTO review_sessions"
            "(id,result_id,source_id,invocation_id,reviewer_id,protocol_artifact_id,"
            "dataset_artifact_id,record_contract_artifact_id,case_id,case_kind,case_group,"
            "reader_role,familiarity_level,familiarity_basis,declared_prior_exposure,"
            "result_presentation_ordinal,started_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                session_id,
                result_id,
                result[0],
                invocation_id,
                reviewer_id,
                protocol_artifact_id,
                dataset_artifact_id,
                record_contract_artifact_id,
                case_id,
                case_kind,
                case_group,
                reader_role,
                familiarity_level,
                familiarity_basis,
                declared_prior_exposure,
                result_presentation_ordinal,
                started_at,
            ),
        )
    return ReviewSession(session_id, result_id, UUID(str(result[0])), reviewer_id)


def save_preparation(
    conn: psycopg.Connection,
    *,
    source_id: UUID,
    reviewer_id: str,
    case_id: str,
    effort: EffortMeasure,
) -> UUID:
    if effort.component != "preparation":
        raise ValueError("review preparation requires the preparation effort component")
    preparation_id = uuid4()
    with conn.transaction():
        conn.execute(
            "INSERT INTO review_preparations(id,source_id,reviewer_id,case_id,effort) "
            "VALUES(%s,%s,%s,%s,%s)",
            (
                preparation_id,
                source_id,
                reviewer_id,
                case_id,
                Jsonb(effort.model_dump(mode="json")),
            ),
        )
    return preparation_id


def get_preparation(
    conn: psycopg.Connection, *, source_id: UUID, reviewer_id: str, case_id: str
) -> tuple[UUID, EffortMeasure] | None:
    """Load the one shareable preparation measurement for a reviewer and case."""
    row = conn.execute(
        "SELECT id,effort FROM review_preparations "
        "WHERE source_id=%s AND reviewer_id=%s AND case_id=%s",
        (source_id, reviewer_id, case_id),
    ).fetchone()
    if row is None:
        return None
    return UUID(str(row[0])), EffortMeasure.model_validate(row[1])


def record_exposure(
    conn: psycopg.Connection,
    *,
    review_session_id: UUID,
    assessment_id: UUID,
    kind: Literal["guided_reveal", "declared_prior_external", "accidental", "general_inspection"],
    presentation_ordinal: int,
    occurred_at: datetime,
) -> UUID:
    exposure_id = uuid4()
    with conn.transaction():
        session = conn.execute(
            "SELECT result_id FROM review_sessions WHERE id=%s FOR UPDATE", (review_session_id,)
        ).fetchone()
        assessment = conn.execute(
            "SELECT target_result_id FROM comparison_assessments WHERE id=%s", (assessment_id,)
        ).fetchone()
        if session is None or assessment is None or session[0] != assessment[0]:
            raise ValueError("exposure assessment must target the review session result")
        if kind == "guided_reveal":
            initial = conn.execute(
                "SELECT 1 FROM review_revisions WHERE review_session_id=%s "
                "AND kind='initial_blind'",
                (review_session_id,),
            ).fetchone()
            if initial is None:
                raise ValueError("guided reveal requires a committed initial revision")
        row = conn.execute(
            "SELECT COALESCE(max(ordinal),0)+1 FROM assessment_exposures "
            "WHERE review_session_id=%s",
            (review_session_id,),
        ).fetchone()
        assert row is not None
        conn.execute(
            "INSERT INTO assessment_exposures"
            "(id,review_session_id,result_id,assessment_id,ordinal,kind,presentation_ordinal,"
            "occurred_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                exposure_id,
                review_session_id,
                session[0],
                assessment_id,
                int(row[0]),
                kind,
                presentation_ordinal,
                occurred_at,
            ),
        )
    return exposure_id


def append_review_revision(
    conn: psycopg.Connection,
    *,
    review_session_id: UUID,
    revision: ReviewRevisionInput,
    exposure_ids_seen: tuple[UUID, ...] = (),
) -> UUID:
    """Append a revision against the current tip and preserve its exact exposure state."""
    revision_id = uuid4()
    with conn.transaction():
        session = conn.execute(
            "SELECT declared_prior_exposure FROM review_sessions WHERE id=%s FOR UPDATE",
            (review_session_id,),
        ).fetchone()
        if session is None:
            raise ValueError("review session not found")
        previous = conn.execute(
            "SELECT id,ordinal FROM review_revisions WHERE review_session_id=%s "
            "ORDER BY ordinal DESC LIMIT 1",
            (review_session_id,),
        ).fetchone()
        ordinal = 1 if previous is None else int(previous[1]) + 1
        if ordinal == 1 and revision.kind != "initial_blind":
            raise ValueError("the first review revision must be initial_blind")
        if ordinal > 1 and revision.kind == "initial_blind":
            raise ValueError("a review session has only one initial revision")
        if revision.blind_status == "confirmed_unexposed" and (
            session[0] != "none_declared" or exposure_ids_seen
        ):
            raise ValueError("confirmed-unexposed requires no declared or recorded exposure")
        exposure_rows: list[tuple[UUID, int]] = []
        for exposure_id in exposure_ids_seen:
            row = conn.execute(
                "SELECT ordinal FROM assessment_exposures WHERE id=%s AND review_session_id=%s",
                (exposure_id, review_session_id),
            ).fetchone()
            if row is None:
                raise ValueError("revision exposure does not belong to the review session")
            exposure_rows.append((exposure_id, int(row[0])))
        conn.execute(
            "INSERT INTO review_revisions"
            "(id,review_session_id,ordinal,previous_revision_id,kind,blind_status,"
            "correctness_label,correctness_rationale,correction,usefulness_status,"
            "usefulness_score,usefulness_rationale,effort,created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                revision_id,
                review_session_id,
                ordinal,
                previous[0] if previous else None,
                revision.kind,
                revision.blind_status,
                revision.correctness_label,
                revision.correctness_rationale,
                revision.correction,
                revision.usefulness_status,
                revision.usefulness_score,
                revision.usefulness_rationale,
                Jsonb([item.model_dump(mode="json") for item in revision.effort]),
                revision.created_at,
            ),
        )
        for seen_ordinal, (exposure_id, _) in enumerate(
            sorted(exposure_rows, key=lambda item: item[1]), 1
        ):
            conn.execute(
                "INSERT INTO review_revision_exposures(revision_id,exposure_id,ordinal) "
                "VALUES(%s,%s,%s)",
                (revision_id, exposure_id, seen_ordinal),
            )
    return revision_id


def complete_review_session(
    conn: psycopg.Connection, review_session_id: UUID, completed_at: datetime
) -> None:
    with conn.transaction():
        row = conn.execute(
            "UPDATE review_sessions SET completed_at=%s "
            "WHERE id=%s AND completed_at IS NULL RETURNING id",
            (completed_at, review_session_id),
        ).fetchone()
        if row is None:
            raise ValueError("review session not found or already completed")


def record_post_assessment_observation(  # noqa: PLR0912
    conn: psycopg.Connection,
    *,
    review_session_id: UUID,
    exposure_id: UUID,
    assessment_id: UUID,
    assessment_status: Literal["not_run", "failed", "inconclusive", "succeeded"],
    assessment_verdict: Literal["agree", "disagree", "inconclusive"] | None = None,
    rationale: str,
    assessment_related_effort: EffortMeasure,
    post_usefulness_status: UsefulnessStatus,
    post_usefulness_score: int | None = None,
    post_usefulness_rationale: str | None = None,
    true_problem_detection: bool | None = None,
    false_alarm: bool | None = None,
    missed_problem: bool | None = None,
    inconclusive: bool | None = None,
    resulting_revision_id: UUID | None = None,
) -> UUID:
    """Persist result-level assessment observations without per-claim annotations."""
    if assessment_related_effort.component != "assessment_related":
        raise ValueError("assessment observation requires assessment-related effort")
    if not rationale.strip():
        raise ValueError("assessment observation rationale must not be blank")
    if assessment_status == "succeeded" and any(
        value is None
        for value in (true_problem_detection, false_alarm, missed_problem, inconclusive)
    ):
        raise ValueError("successful assessment observations require all four boolean outcomes")
    if assessment_status == "succeeded" and assessment_verdict is None:
        raise ValueError("successful assessment observations require a verdict")
    if post_usefulness_status == "measured":
        if post_usefulness_score is None or not (1 <= post_usefulness_score <= 5):
            raise ValueError("measured post-assessment usefulness requires a score from 1 to 5")
        if not post_usefulness_rationale or not post_usefulness_rationale.strip():
            raise ValueError("measured post-assessment usefulness requires rationale")
    elif post_usefulness_score is not None:
        raise ValueError("unmeasured post-assessment usefulness must not have a score")
    observation_id = uuid4()
    with conn.transaction():
        exposure = conn.execute(
            "SELECT e.result_id,e.assessment_id,e.review_session_id "
            "FROM assessment_exposures e WHERE e.id=%s",
            (exposure_id,),
        ).fetchone()
        if exposure is None or exposure[2] != review_session_id or exposure[1] != assessment_id:
            raise ValueError("observation must reference the session's exact exposure")
        assessment = conn.execute(
            "SELECT status,verdict FROM comparison_assessments WHERE id=%s", (assessment_id,)
        ).fetchone()
        if assessment is None:
            raise ValueError("assessment not found")
        stored_status = (
            assessment[0] if assessment[0] in ("succeeded", "inconclusive") else "failed"
        )
        if assessment_status != stored_status or assessment_verdict != assessment[1]:
            raise ValueError("observation status and verdict must match the exact assessment")
        if resulting_revision_id is not None:
            revision = conn.execute(
                "SELECT review_session_id FROM review_revisions WHERE id=%s",
                (resulting_revision_id,),
            ).fetchone()
            if revision is None or revision[0] != review_session_id:
                raise ValueError("observation revision must belong to the review session")
        conn.execute(
            "INSERT INTO post_assessment_observations"
            "(id,review_session_id,exposure_id,assessment_id,resulting_revision_id,"
            "assessment_status,assessment_verdict,true_problem_detection,false_alarm,"
            "missed_problem,inconclusive,"
            "rationale,assessment_related_effort,post_usefulness_status,"
            "post_usefulness_score,post_usefulness_rationale) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                observation_id,
                review_session_id,
                exposure_id,
                assessment_id,
                resulting_revision_id,
                assessment_status,
                assessment_verdict,
                true_problem_detection,
                false_alarm,
                missed_problem,
                inconclusive,
                rationale,
                Jsonb(assessment_related_effort.model_dump(mode="json")),
                post_usefulness_status,
                post_usefulness_score,
                post_usefulness_rationale,
            ),
        )
    return observation_id


def list_review_sessions(
    conn: psycopg.Connection, *, result_id: UUID | None = None
) -> tuple[ReviewSession, ...]:
    """List review identities without collapsing multiple reviews of one result."""
    query = "SELECT id,result_id,source_id,reviewer_id FROM review_sessions"
    params: tuple[UUID, ...] = ()
    if result_id is not None:
        query += " WHERE result_id=%s"
        params = (result_id,)
    query += " ORDER BY started_at,id"
    return tuple(
        ReviewSession(UUID(str(row[0])), UUID(str(row[1])), UUID(str(row[2])), str(row[3]))
        for row in conn.execute(query, params).fetchall()
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _artifact_export(
    conn: psycopg.Connection, artifact_id: UUID | None
) -> dict[str, object] | None:
    if artifact_id is None:
        return None
    row = conn.execute(
        "SELECT id,kind,external_id,version,content,content_hash "
        "FROM evaluation_artifacts WHERE id=%s",
        (artifact_id,),
    ).fetchone()
    if row is None:
        raise ValueError("evaluation artifact not found")
    return {
        "artifact_id": str(row[0]),
        "kind": str(row[1]),
        "id": str(row[2]),
        "version": str(row[3]),
        "sha256": str(row[5]),
        "content_retained": True,
        "content": row[4],
    }


def _historical_repository_locator(current: str, preparation_document: dict[str, object]) -> str:
    snapshot = preparation_document.get("snapshot")
    if isinstance(snapshot, dict):
        locator = snapshot.get("repository")
        if isinstance(locator, str) and locator.strip():
            return locator
    inputs = preparation_document.get("inputs")
    if isinstance(inputs, list):
        for item in inputs:
            if not isinstance(item, dict):
                continue
            urls = item.get("pr_urls")
            if not isinstance(urls, list):
                continue
            for url in urls:
                if isinstance(url, str) and url.startswith("https://github.com/"):
                    parts = url.removeprefix("https://github.com/").split("/")
                    if len(parts) >= 2:
                        return "/".join(parts[:2])
    return current


def load_review_record(
    conn: psycopg.Connection, review_session_id: UUID | str
) -> dict[str, object]:
    """Reload one complete, versioned review payload for inspection or export."""
    session_id = UUID(str(review_session_id))
    row = conn.execute(
        "SELECT s.id,s.result_id,s.source_id,s.invocation_id,s.reviewer_id,"
        "s.protocol_artifact_id,s.dataset_artifact_id,s.record_contract_artifact_id,"
        "s.case_id,s.case_kind,s.case_group,s.reader_role,s.familiarity_level,"
        "s.familiarity_basis,s.declared_prior_exposure,s.result_presentation_ordinal,"
        "s.started_at,s.completed_at,r.github_id,r.owner,r.name,p.number,c.preparation_document "
        "FROM review_sessions s JOIN comparison_sources c ON c.id=s.source_id "
        "JOIN repositories r ON r.id=c.repository_id "
        "LEFT JOIN pull_requests p ON p.id=c.pull_request_id WHERE s.id=%s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError("review session not found")
    protocol = _artifact_export(conn, UUID(str(row[5])))
    dataset = _artifact_export(conn, UUID(str(row[6]))) if row[6] is not None else None
    contract = _artifact_export(conn, UUID(str(row[7])))
    assert protocol is not None and contract is not None
    current_locator = f"{row[19]}/{row[20]}"
    historical_locator = _historical_repository_locator(current_locator, row[22])
    preparation_row = conn.execute(
        "SELECT id,effort FROM review_preparations "
        "WHERE source_id=%s AND reviewer_id=%s AND case_id=%s",
        (row[2], row[4], row[8]),
    ).fetchone()
    preparation: dict[str, object] | None = None
    if preparation_row is not None:
        preparation = {
            "preparation_record_id": str(preparation_row[0]),
            "frozen_source_id": str(row[2]),
            "effort": preparation_row[1],
        }
    exposure_rows = conn.execute(
        "SELECT id,ordinal,assessment_id,kind,presentation_ordinal,occurred_at "
        "FROM assessment_exposures WHERE review_session_id=%s ORDER BY ordinal",
        (session_id,),
    ).fetchall()
    exposures = [
        {
            "exposure_id": str(item[0]),
            "ordinal": int(item[1]),
            "assessment_id": str(item[2]),
            "kind": str(item[3]),
            "presentation_ordinal": int(item[4]),
            "occurred_at": _iso(item[5]),
        }
        for item in exposure_rows
    ]
    revision_rows = conn.execute(
        "SELECT id,ordinal,previous_revision_id,kind,blind_status,correctness_label,"
        "correctness_rationale,correction,usefulness_status,usefulness_score,"
        "usefulness_rationale,effort,created_at FROM review_revisions "
        "WHERE review_session_id=%s ORDER BY ordinal",
        (session_id,),
    ).fetchall()
    revisions: list[dict[str, object]] = []
    for item in revision_rows:
        seen = conn.execute(
            "SELECT exposure_id FROM review_revision_exposures "
            "WHERE revision_id=%s ORDER BY ordinal",
            (item[0],),
        ).fetchall()
        effort = {measure["component"]: measure for measure in item[11]}
        revisions.append(
            {
                "revision_id": str(item[0]),
                "ordinal": int(item[1]),
                "previous_revision_id": str(item[2]) if item[2] is not None else None,
                "kind": str(item[3]),
                "blind_status": str(item[4]),
                "exposure_ids_seen": [str(value[0]) for value in seen],
                "correctness": {
                    "label": item[5],
                    "rationale": item[6],
                    "correction": item[7],
                },
                "usefulness": {
                    "status": str(item[8]),
                    "score": int(item[9]) if item[9] is not None else None,
                    "rationale": item[10],
                },
                "effort": effort,
                "created_at": _iso(item[12]),
            }
        )
    observation_rows = conn.execute(
        "SELECT id,exposure_id,assessment_id,assessment_status,assessment_verdict,"
        "true_problem_detection,false_alarm,missed_problem,inconclusive,rationale,"
        "assessment_related_effort,resulting_revision_id,post_usefulness_status,"
        "post_usefulness_score,post_usefulness_rationale "
        "FROM post_assessment_observations WHERE review_session_id=%s ORDER BY created_at,id",
        (session_id,),
    ).fetchall()
    observations = [
        {
            "observation_id": str(item[0]),
            "exposure_id": str(item[1]),
            "assessment_id": str(item[2]),
            "assessment_status": str(item[3]),
            "assessment_verdict": item[4],
            "true_problem_detection": item[5],
            "false_alarm": item[6],
            "missed_problem": item[7],
            "inconclusive": item[8],
            "rationale": str(item[9]),
            "assessment_related_effort": item[10],
            "post_usefulness": {
                "status": str(item[12]),
                "score": int(item[13]) if item[13] is not None else None,
                "rationale": item[14],
            },
            "resulting_revision_id": str(item[11]) if item[11] is not None else None,
        }
        for item in observation_rows
    ]
    exposed_assessment_ids = {str(item["assessment_id"]) for item in exposures}
    assessment_rows = conn.execute(
        "SELECT id,assessor_recipe_version_id,status,verdict,rationale,error_code "
        "FROM comparison_assessments WHERE target_result_id=%s ORDER BY created_at,id",
        (row[1],),
    ).fetchall()
    assessment_history = [
        {
            "assessment_id": str(item[0]),
            "assessor_recipe_version_id": str(item[1]),
            "status": str(item[2]),
            "exposed": str(item[0]) in exposed_assessment_ids,
            "verdict": item[3] if str(item[0]) in exposed_assessment_ids else None,
            "rationale": item[4] if str(item[0]) in exposed_assessment_ids else None,
            "error_code": item[5],
        }
        for item in assessment_rows
    ]
    return {
        "contract_version": str(contract["id"]),
        "evaluation_id": str(session_id),
        "review_session_id": str(session_id),
        "result_id": str(row[1]),
        "comparison_source_id": str(row[2]),
        "invocation_id": str(row[3]) if row[3] is not None else None,
        "reviewer_id": str(row[4]),
        "protocol": protocol,
        "dataset": dataset,
        "record_contract": contract,
        "case": {
            "id": str(row[8]),
            "kind": str(row[9]),
            "group": str(row[10]),
            "repository_id": int(row[18]),
            "repository_locator_at_selection": historical_locator,
            "pull_request_number": int(row[21]) if row[21] is not None else None,
            "comparison_source_id": str(row[2]),
        },
        "reader_role": str(row[11]),
        "familiarity": {"level": str(row[12]), "basis": str(row[13])},
        "declared_prior_assessment_exposure": str(row[14]),
        "result_presentation_ordinal": int(row[15]),
        "preparation": preparation,
        "exposures": exposures,
        "revisions": revisions,
        "post_assessment_observations": observations,
        "assessment_availability": "not_run" if not assessment_rows else "recorded",
        "assessment_history": assessment_history,
        "started_at": _iso(row[16]),
        "completed_at": _iso(row[17]),
    }


def export_review_record(
    conn: psycopg.Connection, review_session_id: UUID | str
) -> dict[str, object]:
    """Return the reloadable JSON document used by the next evaluation session."""
    return load_review_record(conn, review_session_id)
