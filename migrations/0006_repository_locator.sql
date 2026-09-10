BEGIN;
-- Fail on ambiguous legacy locators; never merge distinct GitHub IDs or history.
CREATE UNIQUE INDEX repositories_locator_case_insensitive
    ON repositories (lower(owner), lower(name));
COMMIT;
