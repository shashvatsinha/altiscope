BEGIN;

-- ---------------------------------------------------------------------------
-- ADR-0010 Deferred Cleanup: decouple from obsolete pr_claims
-- ---------------------------------------------------------------------------

-- 1. aggregate_claim_sources: link directly to pr_summaries instead of pr_claims
ALTER TABLE aggregate_claim_sources DROP CONSTRAINT aggregate_claim_sources_check;
ALTER TABLE aggregate_claim_sources DROP CONSTRAINT aggregate_claim_sources_aggregate_claim_id_pr_claim_id_key;
ALTER TABLE aggregate_claim_sources DROP CONSTRAINT aggregate_claim_sources_pr_claim_id_fkey;
DROP INDEX IF EXISTS aggregate_claim_sources_pr_claim_idx;

ALTER TABLE aggregate_claim_sources DROP COLUMN pr_claim_id;
ALTER TABLE aggregate_claim_sources ADD COLUMN pr_summary_id bigint REFERENCES pr_summaries(id) ON DELETE CASCADE;

ALTER TABLE aggregate_claim_sources ADD CONSTRAINT aggregate_claim_sources_check
    CHECK (num_nonnulls(pr_summary_id, source_aggregate_claim_id) = 1);
ALTER TABLE aggregate_claim_sources ADD CONSTRAINT aggregate_claim_sources_aggregate_claim_id_pr_summary_id_key
    UNIQUE (aggregate_claim_id, pr_summary_id);
CREATE INDEX aggregate_claim_sources_pr_summary_idx ON aggregate_claim_sources (pr_summary_id);

-- 2. verifications: target overall reviews (pr_summaries or aggregate_summaries)
ALTER TABLE verifications DROP CONSTRAINT verifications_check;
ALTER TABLE verifications DROP CONSTRAINT verifications_pr_claim_id_fkey;
ALTER TABLE verifications DROP COLUMN pr_claim_id;
ALTER TABLE verifications ADD COLUMN pr_summary_id bigint REFERENCES pr_summaries(id) ON DELETE CASCADE;
ALTER TABLE verifications ADD COLUMN aggregate_id bigint REFERENCES aggregate_summaries(id) ON DELETE CASCADE;
ALTER TABLE verifications ADD CONSTRAINT verifications_check
    CHECK (num_nonnulls(pr_summary_id, aggregate_id, aggregate_claim_id) = 1);
CREATE INDEX verifications_pr_summary_idx ON verifications (pr_summary_id);
CREATE INDEX verifications_aggregate_idx ON verifications (aggregate_id);

-- 3. flags: remove pr_claim_id reference
ALTER TABLE flags DROP CONSTRAINT flags_check;
ALTER TABLE flags DROP CONSTRAINT flags_pr_claim_id_fkey;
ALTER TABLE flags DROP COLUMN pr_claim_id;
ALTER TABLE flags ADD CONSTRAINT flags_check
    CHECK (num_nonnulls(aggregate_claim_id, pr_summary_id, aggregate_id) = 1);

-- 4. drop obsolete claim scaffold tables without cascade
DROP TABLE pr_claim_evidence;
DROP TABLE pr_claims;

-- ---------------------------------------------------------------------------
-- Milestone 2 Aggregate Provenance & Query Indexing
-- ---------------------------------------------------------------------------

-- 5. aggregate_summaries: add repository reference and altitude-aware cache index
ALTER TABLE aggregate_summaries ADD COLUMN repository_id bigint REFERENCES repositories(id);
CREATE INDEX aggregate_summaries_repo_window_idx ON aggregate_summaries (repository_id, window_start, window_end);

DROP INDEX IF EXISTS aggregate_summaries_cache_idx;
CREATE INDEX aggregate_summaries_cache_idx
    ON aggregate_summaries (input_hash, prompt_version_id, schema_version, model_id, altitude);

-- 6. pull_requests: index repository + merged_at for window lookups on latest snapshots
CREATE INDEX IF NOT EXISTS pull_requests_repo_merged_idx
    ON pull_requests (repository_id, merged_at) WHERE is_latest_snapshot;

COMMIT;
