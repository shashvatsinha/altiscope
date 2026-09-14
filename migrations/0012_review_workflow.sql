BEGIN;

-- A post-assessment usefulness measurement belongs to the observation even when
-- the reviewer does not change the correctness judgment or corrected account.
ALTER TABLE post_assessment_observations
    ADD COLUMN post_usefulness_status text NOT NULL DEFAULT 'unavailable'
        CHECK (post_usefulness_status IN ('measured', 'unavailable', 'not_applicable')),
    ADD COLUMN post_usefulness_score integer CHECK (post_usefulness_score BETWEEN 1 AND 5),
    ADD COLUMN post_usefulness_rationale text;

ALTER TABLE post_assessment_observations
    ADD CONSTRAINT post_assessment_observations_usefulness_check CHECK (
        (post_usefulness_status = 'measured' AND post_usefulness_score IS NOT NULL
         AND post_usefulness_rationale IS NOT NULL
         AND btrim(post_usefulness_rationale) <> '')
        OR
        (post_usefulness_status <> 'measured' AND post_usefulness_score IS NULL)
    );

INSERT INTO schema_migrations (version) VALUES ('0012_review_workflow');
COMMIT;
