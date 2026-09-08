BEGIN;
-- Retain the exact hashed prompt file in addition to its rendered system body.
ALTER TABLE prompt_versions ADD COLUMN source_text text;
-- Every attempt, including a repaired/failed one in hashes-only mode, retains its source.
ALTER TABLE llm_calls ADD COLUMN pull_request_id bigint REFERENCES pull_requests(id);
ALTER TABLE llm_calls ADD COLUMN generation_id uuid;
ALTER TABLE llm_calls ADD COLUMN attempt_ordinal integer CHECK (attempt_ordinal IN (1, 2));
CREATE INDEX llm_calls_pr_generation_idx ON llm_calls(pull_request_id, generation_id);
COMMIT;
