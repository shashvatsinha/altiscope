# GitHub repository identity

GitHub's numeric repository ID is authoritative. `owner/name` is a mutable,
case-insensitive locator. Collection uses GitHub's canonical `full_name` and PR
URL, and follows bounded redirects only within the configured API origin.

Refreshing a known ID updates its current owner/name and default branch, including
when a remote date window is empty. Local queries match the current locator without
regard to case. After a rename, use the new name for `--local-only`; offline mode
cannot discover GitHub redirects. Historical names are not retained as aliases,
because GitHub can reuse them for another repository.

Changing only the locator or PR URL reuses the exact stored snapshot and its PR
report. The comparison uses normalized source content, including the PR's numeric
ID, so existing snapshots written with arbitrary capitalization also work without
rewriting their hashes. Real source edits create another snapshot version. Historical
snapshot JSON, URLs, source hashes, model inputs, reports, and report links remain
unchanged. New source versions retain the current canonical locator and URL.

Aggregate cache keys retain the date window, reader level, exact input report
versions, text, source hashes, URLs, prompt, and generation settings. They omit the
query's mutable repository locator: the exact input versions already identify the
source repository. Thus case variants and renames reuse identical inputs, while
new source/report versions invalidate the cache. Cached reports keep the original
query label and historical links as part of their provenance.

If a locator is still stored under a different GitHub ID, ingestion fails explicitly
without attaching new data to it. Refresh the old repository using its new canonical
name first. Once its locator is released, ingesting the replacement creates a separate
repository and snapshot history. If the old repository is deleted or inaccessible,
an operator must resolve the conflicting locator; Altiscope does not guess its new
identity or delete historical data.

Migration `0006_repository_locator.sql` adds a unique index on lowercase owner/name.
It does not rewrite any source or report. If legacy rows have case-insensitively equal
locators but distinct GitHub IDs, migration fails instead of merging histories.
Resolve those rows against GitHub's current IDs/names before retrying. Aggregate keys
from the previous implementation may miss once after upgrade because their key
included the locator; old aggregate reports remain inspectable.
