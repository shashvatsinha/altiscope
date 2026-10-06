BEGIN;

-- Comparison members store eight fractional digits. Preserve the same precision
-- on their source calls so blended cache rates are not rounded before aggregation.
ALTER TABLE llm_calls ALTER COLUMN cost_usd TYPE numeric(18, 8);

COMMIT;
