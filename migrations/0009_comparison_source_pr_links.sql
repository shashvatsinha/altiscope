BEGIN;

-- A comparison source must retain the navigation links derived from each exact
-- report version. Existing rows are backfilled from their immutable report lineage.
ALTER TABLE comparison_source_inputs ADD COLUMN pr_urls text[] NOT NULL DEFAULT '{}';

UPDATE comparison_source_inputs i
SET pr_urls = ARRAY[p.html_url]
FROM pr_summaries s
JOIN pull_requests p ON p.id = s.pull_request_id
WHERE i.pr_summary_id = s.id;

WITH RECURSIVE report_tree(source_id, root_report_id, report_id) AS (
    SELECT source_id, aggregate_report_id, aggregate_report_id
    FROM comparison_source_inputs
    WHERE aggregate_report_id IS NOT NULL
    UNION
    SELECT t.source_id, t.root_report_id, child.child_report_id
    FROM report_tree t
    JOIN aggregate_report_inputs child ON child.report_id = t.report_id
    WHERE child.child_report_id IS NOT NULL
), links AS (
    SELECT t.source_id, t.root_report_id,
           array_agg(DISTINCT p.html_url ORDER BY p.html_url) AS urls
    FROM report_tree t
    JOIN aggregate_report_inputs input ON input.report_id = t.report_id
    JOIN pr_summaries s ON s.id = input.pr_summary_id
    JOIN pull_requests p ON p.id = s.pull_request_id
    GROUP BY t.source_id, t.root_report_id
)
UPDATE comparison_source_inputs i
SET pr_urls = links.urls
FROM links
WHERE i.source_id = links.source_id
  AND i.aggregate_report_id = links.root_report_id;

COMMIT;
