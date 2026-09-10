# Database migrations

Altiscope applies each numbered SQL file and its `schema_migrations` row in one
Postgres transaction. Migration files keep their historical `BEGIN` and `COMMIT`;
the runner validates that wrapper and inserts the version row immediately before the
final `COMMIT`. A failure in either the migration body or version insert rolls back
both. Each file commits separately, and a run with no pending files makes no changes.

## Recovering a historical missing marker

Runner versions before this transaction fix could commit a migration and then fail
before recording its version. Re-running such a database fails on the first
non-idempotent statement. The runner deliberately does not infer that the whole
migration completed: doing so is unsafe for data-changing migrations such as 0004.
It rolls back the failed retry and leaves both the existing schema and missing marker
unchanged.

Use this bounded recovery procedure for one missing version at a time:

1. Stop application and migration writers, take a database backup, and test recovery
   on a restored copy first.
2. Find the earliest missing version by comparing `SELECT version FROM
   schema_migrations ORDER BY version` with the immutable files in `migrations/`.
3. Have a Postgres operator verify every statement and data-preservation requirement
   in that exact migration against the catalogs and retained rows. For 0004, verify
   all renamed/replaced constraints, columns, and indexes as well as the absence of
   `pr_claims` and `pr_claim_evidence`; do not rerun its destructive statements.
4. If any statement is absent or its completion is uncertain, restore the backup or
   write and review a one-off repair for that statement. Do not add the marker yet.
5. Only after the complete post-migration state is verified, record that single
   version while writers remain stopped:

   ```sql
   BEGIN;
   LOCK TABLE schema_migrations IN ACCESS EXCLUSIVE MODE;
   INSERT INTO schema_migrations (version) VALUES ('0004_aggregate_provenance');
   COMMIT;
   ```

6. Run `altiscope db migrate`, validate the application data, then resume writers.

Replace the example only with the exact verified missing filename stem. Never mark a
later version in the same recovery transaction or edit an existing migration file.
