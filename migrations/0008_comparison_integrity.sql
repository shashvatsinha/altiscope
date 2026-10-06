BEGIN;

-- Tighten nullable CHECK expressions introduced by 0007. PostgreSQL CHECK
-- constraints accept NULL, so hash/error presence must be explicit.
ALTER TABLE comparison_run_results DROP CONSTRAINT comparison_run_results_check;
ALTER TABLE comparison_run_results ADD CONSTRAINT comparison_run_results_check CHECK (
    (status = 'succeeded' AND output_document IS NOT NULL AND output_hash IS NOT NULL
     AND length(output_hash) = 64 AND error_code IS NULL AND error_message IS NULL)
    OR
    (status <> 'succeeded' AND output_document IS NULL AND output_hash IS NULL
     AND error_code IS NOT NULL)
);

ALTER TABLE comparison_assessments DROP CONSTRAINT comparison_assessments_check;
ALTER TABLE comparison_assessments ADD CONSTRAINT comparison_assessments_check CHECK (
    (status IN ('succeeded', 'inconclusive') AND verdict IS NOT NULL
     AND rationale IS NOT NULL AND output_document IS NOT NULL AND output_hash IS NOT NULL
     AND length(output_hash) = 64 AND error_code IS NULL)
    OR
    (status NOT IN ('succeeded', 'inconclusive') AND verdict IS NULL
     AND output_document IS NULL AND output_hash IS NULL AND error_code IS NOT NULL)
);

ALTER TABLE comparison_run_results ADD CONSTRAINT comparison_run_results_id_source_key
    UNIQUE (id, source_id);
ALTER TABLE review_sessions ADD CONSTRAINT review_sessions_result_source_fkey
    FOREIGN KEY (result_id, source_id) REFERENCES comparison_run_results(id, source_id);

COMMIT;
