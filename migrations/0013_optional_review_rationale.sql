BEGIN;

-- #48 permits an optional whole-result rationale. The protocol still prompts
-- for one, but storage must faithfully retain an omitted value instead of
-- manufacturing text.
DO $$
DECLARE
    constraint_name text;
BEGIN
    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = 'review_revisions'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%correctness_label IS NULL%';
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE review_revisions DROP CONSTRAINT %I', constraint_name);
    END IF;
END $$;

INSERT INTO schema_migrations (version) VALUES ('0013_optional_review_rationale');
COMMIT;
