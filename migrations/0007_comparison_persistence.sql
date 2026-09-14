BEGIN;

-- M3 keeps experimental records separate from production reports and caches.
-- UUIDs are allocated by the application so this migration needs no extension.

ALTER TABLE llm_calls ADD COLUMN usage_status text
    CHECK (usage_status IN ('measured', 'unavailable'));
ALTER TABLE llm_calls ADD COLUMN cost_status text
    CHECK (cost_status IN ('complete', 'partial', 'unavailable'));
ALTER TABLE llm_calls ADD COLUMN pricing_basis jsonb;
ALTER TABLE llm_calls ADD COLUMN actual_output_mode text
    CHECK (actual_output_mode IN ('native', 'json_mode', 'prompt'));

CREATE TABLE output_schema_versions (
    id uuid PRIMARY KEY,
    stage text NOT NULL CHECK (stage IN ('pr_summary', 'aggregate', 'verify')),
    contract_id text NOT NULL CHECK (btrim(contract_id) <> ''),
    version integer NOT NULL CHECK (version > 0),
    schema_document jsonb NOT NULL,
    schema_hash text NOT NULL CHECK (length(schema_hash) = 64),
    validator_version text NOT NULL CHECK (btrim(validator_version) <> ''),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (stage, contract_id, version),
    UNIQUE (id, stage)
);

CREATE TABLE recipe_versions (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (btrim(name) <> ''),
    version integer NOT NULL CHECK (version > 0),
    stage text NOT NULL CHECK (stage IN ('pr_summary', 'aggregate', 'verify')),
    prompt_version_id bigint NOT NULL REFERENCES prompt_versions(id),
    output_schema_version_id uuid NOT NULL REFERENCES output_schema_versions(id),
    configuration_format_version integer NOT NULL CHECK (configuration_format_version > 0),
    configuration jsonb NOT NULL,
    configuration_hash text NOT NULL CHECK (length(configuration_hash) = 64),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (name, version),
    UNIQUE (id, stage)
);
CREATE INDEX recipe_versions_name_latest_idx ON recipe_versions(name, version DESC);

CREATE TABLE comparison_sources (
    id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('pr', 'aggregate')),
    stage text NOT NULL CHECK (stage IN ('pr_summary', 'aggregate')),
    repository_id bigint NOT NULL REFERENCES repositories(id),
    pull_request_id bigint REFERENCES pull_requests(id),
    source_format_version text NOT NULL CHECK (btrim(source_format_version) <> ''),
    preparation_contract jsonb NOT NULL,
    preparation_document jsonb NOT NULL,
    prepared_text text NOT NULL,
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    prepared_text_hash text NOT NULL CHECK (length(prepared_text_hash) = 64),
    query jsonb,
    altitude text CHECK (altitude IN ('ic', 'manager', 'exec')),
    experiment_scope text NOT NULL CHECK (experiment_scope = 'single_step'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, stage),
    CHECK (
        (kind = 'pr' AND stage = 'pr_summary' AND pull_request_id IS NOT NULL
         AND query IS NULL AND altitude IS NULL)
        OR
        (kind = 'aggregate' AND stage = 'aggregate' AND pull_request_id IS NULL
         AND query IS NOT NULL AND altitude IS NOT NULL)
    )
);
CREATE INDEX comparison_sources_repository_idx ON comparison_sources(repository_id, created_at);

CREATE TABLE comparison_source_inputs (
    source_id uuid NOT NULL REFERENCES comparison_sources(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    pr_summary_id bigint REFERENCES pr_summaries(id),
    aggregate_report_id uuid REFERENCES aggregate_reports(id),
    input_kind text NOT NULL CHECK (input_kind IN ('pr_summary', 'aggregate_report')),
    rendered_text text NOT NULL,
    rendered_text_hash text NOT NULL CHECK (length(rendered_text_hash) = 64),
    source_hash text NOT NULL CHECK (length(source_hash) = 64),
    PRIMARY KEY (source_id, ordinal),
    UNIQUE (source_id, pr_summary_id),
    UNIQUE (source_id, aggregate_report_id),
    CHECK (num_nonnulls(pr_summary_id, aggregate_report_id) = 1),
    CHECK (
        (input_kind = 'pr_summary' AND pr_summary_id IS NOT NULL)
        OR (input_kind = 'aggregate_report' AND aggregate_report_id IS NOT NULL)
    )
);

CREATE TABLE evaluation_artifacts (
    id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('protocol', 'dataset', 'record_contract')),
    external_id text NOT NULL CHECK (btrim(external_id) <> ''),
    version text NOT NULL CHECK (btrim(version) <> ''),
    content jsonb NOT NULL,
    content_hash text NOT NULL CHECK (length(content_hash) = 64),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (kind, external_id, version)
);

CREATE TABLE comparison_invocations (
    id uuid PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES comparison_sources(id),
    stage text NOT NULL CHECK (stage IN ('pr_summary', 'aggregate')),
    experiment_scope text NOT NULL CHECK (experiment_scope = 'single_step'),
    force_rerun boolean NOT NULL,
    retention text NOT NULL CHECK (retention IN ('full', 'hashes_only')),
    protocol_artifact_id uuid REFERENCES evaluation_artifacts(id),
    execution_build text NOT NULL CHECK (btrim(execution_build) <> ''),
    specification jsonb NOT NULL,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'incomplete')),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (id, source_id, stage),
    CHECK ((status = 'running') = (completed_at IS NULL))
);

CREATE TABLE comparison_members (
    id uuid PRIMARY KEY,
    invocation_id uuid NOT NULL REFERENCES comparison_invocations(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    recipe_version_id uuid NOT NULL REFERENCES recipe_versions(id),
    disposition text NOT NULL DEFAULT 'pending'
        CHECK (disposition IN ('pending', 'generated', 'reused')),
    result_id uuid,
    current_call_count integer NOT NULL DEFAULT 0 CHECK (current_call_count >= 0),
    current_cost_usd numeric(18, 8),
    current_cost_status text NOT NULL DEFAULT 'not_incurred'
        CHECK (current_cost_status IN ('not_incurred', 'complete', 'partial', 'unavailable')),
    finalized_at timestamptz,
    UNIQUE (invocation_id, ordinal),
    UNIQUE (invocation_id, recipe_version_id),
    UNIQUE (id, invocation_id, recipe_version_id),
    CHECK (
        (disposition = 'pending' AND result_id IS NULL AND finalized_at IS NULL)
        OR (disposition IN ('generated', 'reused') AND result_id IS NOT NULL
            AND finalized_at IS NOT NULL)
    ),
    CHECK (disposition <> 'reused' OR current_call_count = 0),
    CHECK (disposition <> 'reused' OR current_cost_status = 'not_incurred')
);

CREATE TABLE comparison_run_results (
    id uuid PRIMARY KEY,
    origin_member_id uuid NOT NULL UNIQUE,
    source_id uuid NOT NULL REFERENCES comparison_sources(id),
    recipe_version_id uuid NOT NULL REFERENCES recipe_versions(id),
    output_schema_version_id uuid NOT NULL REFERENCES output_schema_versions(id),
    cache_namespace text NOT NULL CHECK (cache_namespace = 'comparison'),
    cache_key_version integer NOT NULL CHECK (cache_key_version > 0),
    cache_key text NOT NULL CHECK (length(cache_key) = 64),
    status text NOT NULL CHECK (
        status IN ('succeeded', 'preflight_failed', 'invalid_output', 'refused', 'failed')
    ),
    output_document jsonb,
    output_hash text,
    error_code text,
    error_message text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, source_id, recipe_version_id),
    CHECK (finished_at >= started_at),
    CHECK (
        (status = 'succeeded' AND output_document IS NOT NULL AND length(output_hash) = 64
         AND error_code IS NULL AND error_message IS NULL)
        OR
        (status <> 'succeeded' AND output_document IS NULL AND output_hash IS NULL
         AND error_code IS NOT NULL)
    )
);
CREATE INDEX comparison_results_cache_idx
    ON comparison_run_results(cache_key, created_at DESC, id DESC)
    WHERE status = 'succeeded';

ALTER TABLE comparison_members ADD CONSTRAINT comparison_members_result_fkey
    FOREIGN KEY (result_id) REFERENCES comparison_run_results(id);

CREATE TABLE comparison_result_calls (
    result_id uuid NOT NULL REFERENCES comparison_run_results(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    call_id bigint NOT NULL UNIQUE REFERENCES llm_calls(id),
    PRIMARY KEY (result_id, ordinal)
);

CREATE TABLE comparison_assessments (
    id uuid PRIMARY KEY,
    target_result_id uuid NOT NULL REFERENCES comparison_run_results(id),
    assessor_recipe_version_id uuid NOT NULL REFERENCES recipe_versions(id),
    requesting_invocation_id uuid REFERENCES comparison_invocations(id),
    requesting_member_id uuid REFERENCES comparison_members(id),
    request_identity uuid NOT NULL UNIQUE,
    input_document jsonb NOT NULL,
    input_hash text NOT NULL CHECK (length(input_hash) = 64),
    independence_evidence jsonb NOT NULL,
    status text NOT NULL CHECK (
        status IN ('succeeded', 'preflight_failed', 'invalid_output', 'refused', 'failed',
                   'inconclusive')
    ),
    verdict text CHECK (verdict IN ('agree', 'disagree', 'inconclusive')),
    rationale text,
    output_schema_version_id uuid REFERENCES output_schema_versions(id),
    output_document jsonb,
    output_hash text,
    error_code text,
    error_message text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (finished_at >= started_at),
    CHECK ((requesting_member_id IS NULL) OR (requesting_invocation_id IS NOT NULL)),
    CHECK (
        (status IN ('succeeded', 'inconclusive') AND verdict IS NOT NULL
         AND rationale IS NOT NULL AND output_document IS NOT NULL
         AND length(output_hash) = 64 AND error_code IS NULL)
        OR
        (status NOT IN ('succeeded', 'inconclusive') AND verdict IS NULL
         AND output_document IS NULL AND output_hash IS NULL AND error_code IS NOT NULL)
    )
);

CREATE TABLE comparison_assessment_calls (
    assessment_id uuid NOT NULL REFERENCES comparison_assessments(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    call_id bigint NOT NULL UNIQUE REFERENCES llm_calls(id),
    PRIMARY KEY (assessment_id, ordinal)
);

CREATE TABLE llm_call_owners (
    call_id bigint PRIMARY KEY REFERENCES llm_calls(id),
    owner_kind text NOT NULL CHECK (owner_kind IN ('comparison_result', 'assessment')),
    result_id uuid REFERENCES comparison_run_results(id),
    assessment_id uuid REFERENCES comparison_assessments(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    UNIQUE (result_id, ordinal),
    UNIQUE (assessment_id, ordinal),
    CHECK (
        (owner_kind = 'comparison_result' AND result_id IS NOT NULL AND assessment_id IS NULL)
        OR (owner_kind = 'assessment' AND assessment_id IS NOT NULL AND result_id IS NULL)
    )
);

CREATE TABLE review_sessions (
    id uuid PRIMARY KEY,
    result_id uuid NOT NULL REFERENCES comparison_run_results(id),
    source_id uuid NOT NULL REFERENCES comparison_sources(id),
    invocation_id uuid REFERENCES comparison_invocations(id),
    reviewer_id text NOT NULL CHECK (btrim(reviewer_id) <> ''),
    protocol_artifact_id uuid NOT NULL REFERENCES evaluation_artifacts(id),
    dataset_artifact_id uuid REFERENCES evaluation_artifacts(id),
    record_contract_artifact_id uuid NOT NULL REFERENCES evaluation_artifacts(id),
    case_id text NOT NULL CHECK (btrim(case_id) <> ''),
    case_kind text NOT NULL CHECK (case_kind IN ('pr', 'aggregate')),
    case_group text NOT NULL CHECK (case_group IN ('development', 'held_out')),
    reader_role text NOT NULL CHECK (reader_role IN ('ic', 'manager', 'exec')),
    familiarity_level text NOT NULL
        CHECK (familiarity_level IN ('direct', 'repository', 'domain', 'prepared', 'none')),
    familiarity_basis text NOT NULL CHECK (btrim(familiarity_basis) <> ''),
    declared_prior_exposure text NOT NULL
        CHECK (declared_prior_exposure IN ('none_declared', 'known', 'unknown')),
    result_presentation_ordinal integer NOT NULL CHECK (result_presentation_ordinal > 0),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    UNIQUE (id, result_id, reviewer_id)
);

CREATE TABLE review_preparations (
    id uuid PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES comparison_sources(id),
    reviewer_id text NOT NULL CHECK (btrim(reviewer_id) <> ''),
    case_id text NOT NULL CHECK (btrim(case_id) <> ''),
    effort jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (source_id, reviewer_id, case_id)
);

CREATE TABLE assessment_exposures (
    id uuid PRIMARY KEY,
    review_session_id uuid NOT NULL REFERENCES review_sessions(id),
    result_id uuid NOT NULL REFERENCES comparison_run_results(id),
    assessment_id uuid NOT NULL REFERENCES comparison_assessments(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    kind text NOT NULL CHECK (
        kind IN ('guided_reveal', 'declared_prior_external', 'accidental', 'general_inspection')
    ),
    presentation_ordinal integer NOT NULL CHECK (presentation_ordinal > 0),
    occurred_at timestamptz NOT NULL,
    UNIQUE (review_session_id, ordinal),
    UNIQUE (id, review_session_id)
);

CREATE TABLE review_revisions (
    id uuid PRIMARY KEY,
    review_session_id uuid NOT NULL REFERENCES review_sessions(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    previous_revision_id uuid REFERENCES review_revisions(id),
    kind text NOT NULL CHECK (kind IN ('initial_blind', 'post_assessment', 'adjudication')),
    blind_status text NOT NULL
        CHECK (blind_status IN ('confirmed_unexposed', 'known_exposed', 'unknown')),
    correctness_label text CHECK (correctness_label IN ('correct', 'incorrect', 'unclear')),
    correctness_rationale text,
    correction text,
    usefulness_status text NOT NULL
        CHECK (usefulness_status IN ('measured', 'unavailable', 'not_applicable')),
    usefulness_score integer CHECK (usefulness_score BETWEEN 1 AND 5),
    usefulness_rationale text,
    effort jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (review_session_id, ordinal),
    UNIQUE (id, review_session_id),
    CHECK (
        (usefulness_status = 'measured' AND usefulness_score IS NOT NULL
         AND usefulness_rationale IS NOT NULL)
        OR (usefulness_status <> 'measured' AND usefulness_score IS NULL)
    ),
    CHECK (correctness_label IS NULL OR correctness_rationale IS NOT NULL)
);

CREATE TABLE review_revision_exposures (
    revision_id uuid NOT NULL REFERENCES review_revisions(id),
    exposure_id uuid NOT NULL REFERENCES assessment_exposures(id),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    PRIMARY KEY (revision_id, ordinal),
    UNIQUE (revision_id, exposure_id)
);

CREATE TABLE post_assessment_observations (
    id uuid PRIMARY KEY,
    review_session_id uuid NOT NULL REFERENCES review_sessions(id),
    exposure_id uuid NOT NULL UNIQUE REFERENCES assessment_exposures(id),
    assessment_id uuid NOT NULL REFERENCES comparison_assessments(id),
    resulting_revision_id uuid REFERENCES review_revisions(id),
    assessment_status text NOT NULL
        CHECK (assessment_status IN ('not_run', 'failed', 'inconclusive', 'succeeded')),
    assessment_verdict text CHECK (assessment_verdict IN ('agree', 'disagree', 'inconclusive')),
    true_problem_detection boolean,
    false_alarm boolean,
    missed_problem boolean,
    inconclusive boolean,
    rationale text NOT NULL CHECK (btrim(rationale) <> ''),
    assessment_related_effort jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Frozen rows cannot be reinterpreted after creation. Invocation/member lifecycle
-- and review completion remain intentionally mutable through their checked APIs.
CREATE FUNCTION reject_m3_immutable_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DO $$ DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'output_schema_versions', 'recipe_versions', 'comparison_sources',
        'comparison_source_inputs', 'evaluation_artifacts', 'comparison_run_results',
        'comparison_result_calls', 'comparison_assessments', 'comparison_assessment_calls',
        'llm_call_owners',
        'review_preparations', 'assessment_exposures', 'review_revisions',
        'review_revision_exposures', 'post_assessment_observations'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION reject_m3_immutable_update()', table_name, table_name
        );
    END LOOP;
END $$;

COMMIT;
