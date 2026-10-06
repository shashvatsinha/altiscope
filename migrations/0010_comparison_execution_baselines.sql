BEGIN;

-- A baseline is an immutable recipe version whose generation condition matches
-- one or more candidate recipes except for the prompt.  Assignments are explicit
-- so comparison expansion never guesses which historical recipe is the baseline.
CREATE TABLE baseline_recipe_versions (
    recipe_version_id uuid PRIMARY KEY REFERENCES recipe_versions(id),
    generation_condition_hash text NOT NULL CHECK (length(generation_condition_hash) = 64),
    prompt_class text NOT NULL CHECK (prompt_class = 'minimal_summary'),
    rationale text NOT NULL CHECK (btrim(rationale) <> ''),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX baseline_recipe_condition_idx
    ON baseline_recipe_versions(generation_condition_hash, recipe_version_id);

CREATE TABLE recipe_primary_baselines (
    recipe_version_id uuid PRIMARY KEY REFERENCES recipe_versions(id),
    baseline_recipe_version_id uuid NOT NULL REFERENCES baseline_recipe_versions(recipe_version_id),
    rationale text NOT NULL CHECK (btrim(rationale) <> ''),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (recipe_version_id <> baseline_recipe_version_id)
);

-- #49 can distinguish ordinary candidates, prompt-only primary baselines and
-- explicitly model-changing conditions without reconstructing labels from names.
ALTER TABLE comparison_members ADD COLUMN condition_label text NOT NULL DEFAULT 'candidate'
    CHECK (condition_label IN ('candidate', 'primary_baseline', 'model_comparison'));

CREATE TABLE comparison_member_baseline_targets (
    member_id uuid NOT NULL REFERENCES comparison_members(id),
    recipe_version_id uuid NOT NULL REFERENCES recipe_versions(id),
    PRIMARY KEY (member_id, recipe_version_id)
);

COMMIT;
