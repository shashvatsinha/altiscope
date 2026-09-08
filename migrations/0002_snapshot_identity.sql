BEGIN;
ALTER TABLE pull_requests ADD COLUMN source_hash text;
ALTER TABLE pull_requests ADD COLUMN normalized_snapshot jsonb;
CREATE UNIQUE INDEX pull_requests_latest_unique
    ON pull_requests(repository_id, number) WHERE is_latest_snapshot;
ALTER TABLE llm_calls ADD COLUMN response_hash text;
ALTER TABLE llm_calls ADD COLUMN selected_config jsonb;
ALTER TABLE pr_summaries ADD COLUMN semantic_status text NOT NULL DEFAULT 'unverified'
    CHECK (semantic_status IN ('unverified', 'verified'));
-- Every generation run is retained; the partial current index selects publication.
DO $$ DECLARE constraint_name text;
BEGIN
    FOR constraint_name IN SELECT conname FROM pg_constraint
        WHERE conrelid = 'pr_summaries'::regclass AND contype = 'u'
    LOOP
        EXECUTE format('ALTER TABLE pr_summaries DROP CONSTRAINT %I', constraint_name);
    END LOOP;
END $$;
COMMIT;
