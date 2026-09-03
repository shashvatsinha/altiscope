-- Altiscope initial schema.
-- Read this file as the provenance contract. See docs/adr/0004-provenance-as-rows.md.
--
-- Conventions
--   * ids are bigint identity columns; external ids (GitHub) are stored alongside.
--   * timestamps are timestamptz, UTC.
--   * snapshot tables are append-only; rows are never updated after insert except for
--     bookkeeping flags noted inline.
--   * polymorphic references use nullable FK columns plus a CHECK that exactly one is set.

BEGIN;

CREATE TABLE schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Identity: repositories, people, teams (temporal membership)
-- ---------------------------------------------------------------------------

CREATE TABLE repositories (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    github_id        bigint NOT NULL UNIQUE,
    owner            text NOT NULL,
    name             text NOT NULL,
    default_branch   text NOT NULL,
    visibility       text NOT NULL CHECK (visibility IN ('public', 'private', 'internal')),
    installation_id  bigint,                       -- GitHub App installation, null for PAT
    enabled          boolean NOT NULL DEFAULT true, -- bookkeeping, may be updated
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner, name)
);

CREATE TABLE people (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    github_id     bigint UNIQUE,
    github_login  text NOT NULL UNIQUE,
    display_name  text,
    email         text,
    is_bot        boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE teams (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug            text NOT NULL UNIQUE,
    name            text NOT NULL,
    source          text NOT NULL CHECK (source IN ('github', 'manual', 'import')),
    github_team_id  bigint UNIQUE,
    parent_team_id  bigint REFERENCES teams(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Membership is temporal so that "the team's work in Q2" resolves membership as of each
-- PR's merge date rather than as of today.
CREATE TABLE team_memberships (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_id     bigint NOT NULL REFERENCES teams(id),
    person_id   bigint NOT NULL REFERENCES people(id),
    valid_from  timestamptz NOT NULL,
    valid_to    timestamptz,                          -- null = current
    source      text NOT NULL CHECK (source IN ('github', 'manual', 'import')),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX team_memberships_person_idx ON team_memberships (person_id, valid_from, valid_to);
CREATE INDEX team_memberships_team_idx   ON team_memberships (team_id, valid_from, valid_to);

-- ---------------------------------------------------------------------------
-- PR snapshots (append-only source of truth)
-- ---------------------------------------------------------------------------

CREATE TABLE pull_requests (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repository_id      bigint NOT NULL REFERENCES repositories(id),
    number             integer NOT NULL,
    github_id          bigint NOT NULL,
    snapshot_version   integer NOT NULL DEFAULT 1,    -- re-fetch writes a new row
    is_latest_snapshot boolean NOT NULL DEFAULT true, -- bookkeeping, may be updated
    title              text NOT NULL,
    body               text NOT NULL DEFAULT '',
    author_id          bigint NOT NULL REFERENCES people(id),
    state              text NOT NULL CHECK (state IN ('open', 'closed', 'merged')),
    is_draft           boolean NOT NULL DEFAULT false,
    base_ref           text NOT NULL,
    head_ref           text NOT NULL,
    merge_commit_sha   text,
    created_at         timestamptz NOT NULL,
    updated_at         timestamptz NOT NULL,
    closed_at          timestamptz,
    merged_at          timestamptz,
    merged_by_id       bigint REFERENCES people(id),
    additions          integer NOT NULL,
    deletions          integer NOT NULL,
    changed_files      integer NOT NULL,
    labels             text[] NOT NULL DEFAULT '{}',
    html_url           text NOT NULL,
    fetched_at         timestamptz NOT NULL DEFAULT now(),
    raw                jsonb NOT NULL,                -- full API payload for audit
    UNIQUE (repository_id, number, snapshot_version),
    CHECK (state <> 'merged' OR merged_at IS NOT NULL)
);
CREATE INDEX pull_requests_merged_idx ON pull_requests (merged_at) WHERE is_latest_snapshot;
CREATE INDEX pull_requests_author_idx ON pull_requests (author_id, merged_at) WHERE is_latest_snapshot;

CREATE TABLE pr_files (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pull_request_id  bigint NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    path             text NOT NULL,
    previous_path    text,
    status           text NOT NULL CHECK (status IN ('added', 'modified', 'removed', 'renamed', 'copied', 'changed', 'unchanged')),
    additions        integer NOT NULL,
    deletions        integer NOT NULL,
    patch            text,                            -- null when GitHub omits it (binary/oversize)
    is_binary        boolean NOT NULL DEFAULT false,
    -- diff policy outcome, computed at ingest; see altiscope.ingest.diff_policy
    included         boolean NOT NULL,
    exclusion_reason text CHECK (exclusion_reason IN ('lockfile', 'generated', 'vendored', 'binary', 'minified', 'oversize', 'no_patch')),
    CHECK (included = (exclusion_reason IS NULL)),
    UNIQUE (pull_request_id, path)
);

CREATE TABLE pr_commits (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pull_request_id  bigint NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    sha              text NOT NULL,
    message          text NOT NULL,
    author_id        bigint REFERENCES people(id),
    authored_at      timestamptz,
    UNIQUE (pull_request_id, sha)
);

CREATE TABLE pr_reviews (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pull_request_id  bigint NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    github_id        bigint NOT NULL,
    author_id        bigint NOT NULL REFERENCES people(id),
    state            text NOT NULL CHECK (state IN ('APPROVED', 'CHANGES_REQUESTED', 'COMMENTED', 'DISMISSED', 'PENDING')),
    body             text NOT NULL DEFAULT '',
    submitted_at     timestamptz,
    UNIQUE (pull_request_id, github_id)
);

CREATE TABLE pr_comments (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pull_request_id  bigint NOT NULL REFERENCES pull_requests(id) ON DELETE CASCADE,
    github_id        bigint NOT NULL,
    kind             text NOT NULL CHECK (kind IN ('issue', 'review')),  -- conversation vs inline
    author_id        bigint NOT NULL REFERENCES people(id),
    path             text,                            -- inline comments only
    line             integer,
    in_reply_to_github_id bigint,
    body             text NOT NULL,
    created_at       timestamptz NOT NULL,
    UNIQUE (pull_request_id, kind, github_id)
);

-- ---------------------------------------------------------------------------
-- LLM provenance: prompts and calls
-- ---------------------------------------------------------------------------

CREATE TABLE prompt_versions (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stage         text NOT NULL CHECK (stage IN ('pr_summary', 'aggregate', 'verify')),
    name          text NOT NULL,                      -- e.g. "v1"
    content_hash  text NOT NULL,                      -- sha256 of the prompt file
    content       text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (stage, content_hash)
);

CREATE TABLE llm_calls (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stage                    text NOT NULL CHECK (stage IN ('pr_summary', 'aggregate', 'verify')),
    provider                 text NOT NULL,
    model_id                 text NOT NULL,
    prompt_version_id        bigint NOT NULL REFERENCES prompt_versions(id),
    schema_version           integer NOT NULL,
    effort                   text,
    -- routing provenance (principle 6)
    routing_rule             text NOT NULL,           -- which registry rule fired
    routing_reason           text NOT NULL,           -- human-readable
    routing_candidates       text[] NOT NULL,         -- models considered, in order
    estimated_input_tokens   integer NOT NULL,
    -- usage
    input_tokens             integer,
    output_tokens            integer,
    cache_read_tokens        integer,
    cache_write_tokens       integer,
    cost_usd                 numeric(12, 6),
    latency_ms               integer,
    provider_request_id      text,
    stop_reason              text,
    status                   text NOT NULL CHECK (status IN ('succeeded', 'failed', 'refused', 'invalid_output')),
    error                    text,
    -- payloads, retention configurable (docs/ARCHITECTURE.md section 8)
    request_hash             text NOT NULL,
    request_payload          jsonb,
    response_text            text,
    started_at               timestamptz NOT NULL,
    finished_at              timestamptz
);
CREATE INDEX llm_calls_stage_model_idx ON llm_calls (stage, model_id, started_at);

-- ---------------------------------------------------------------------------
-- Atomic summaries and their claims (one per merged PR per prompt/schema/model)
-- ---------------------------------------------------------------------------

CREATE TABLE pr_summaries (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pull_request_id    bigint NOT NULL REFERENCES pull_requests(id),
    llm_call_id        bigint NOT NULL REFERENCES llm_calls(id),
    prompt_version_id  bigint NOT NULL REFERENCES prompt_versions(id),
    schema_version     integer NOT NULL,
    model_id           text NOT NULL,
    is_current         boolean NOT NULL DEFAULT true,   -- bookkeeping, may be updated
    status             text NOT NULL CHECK (status IN ('published', 'needs_review', 'rejected')),
    headline           text NOT NULL,
    narrative          text NOT NULL,
    facts              jsonb NOT NULL,                  -- computed in code, never by the model
    input_manifest     jsonb NOT NULL,                  -- what the model was shown / not shown
    uncertainties      jsonb NOT NULL DEFAULT '[]',
    description_vs_diff jsonb NOT NULL DEFAULT '[]',
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (pull_request_id, prompt_version_id, schema_version, model_id)
);
CREATE UNIQUE INDEX pr_summaries_current_idx ON pr_summaries (pull_request_id) WHERE is_current;

CREATE TABLE pr_claims (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pr_summary_id  bigint NOT NULL REFERENCES pr_summaries(id) ON DELETE CASCADE,
    ordinal        integer NOT NULL,
    kind           text NOT NULL CHECK (kind IN ('feature', 'bugfix', 'refactor', 'infra', 'test', 'docs', 'perf', 'security', 'dependency', 'chore', 'other')),
    text           text NOT NULL,
    UNIQUE (pr_summary_id, ordinal)
);

CREATE TABLE pr_claim_evidence (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pr_claim_id      bigint NOT NULL REFERENCES pr_claims(id) ON DELETE CASCADE,
    evidence_type    text NOT NULL CHECK (evidence_type IN ('file', 'hunk', 'description', 'title', 'review_comment', 'commit')),
    pr_file_id       bigint REFERENCES pr_files(id),
    hunk_header      text,                            -- "@@ -a,b +c,d @@" when evidence_type = 'hunk'
    pr_comment_id    bigint REFERENCES pr_comments(id),
    pr_commit_id     bigint REFERENCES pr_commits(id),
    quote            text,                            -- verbatim span for description/title/comment
    CHECK (
        (evidence_type IN ('file', 'hunk')          AND pr_file_id IS NOT NULL AND pr_comment_id IS NULL AND pr_commit_id IS NULL) OR
        (evidence_type = 'review_comment'           AND pr_comment_id IS NOT NULL AND pr_file_id IS NULL AND pr_commit_id IS NULL) OR
        (evidence_type = 'commit'                   AND pr_commit_id IS NOT NULL AND pr_file_id IS NULL AND pr_comment_id IS NULL) OR
        (evidence_type IN ('description', 'title')  AND quote IS NOT NULL AND pr_file_id IS NULL AND pr_comment_id IS NULL AND pr_commit_id IS NULL)
    ),
    CHECK (evidence_type <> 'hunk' OR hunk_header IS NOT NULL)
);
CREATE INDEX pr_claim_evidence_claim_idx ON pr_claim_evidence (pr_claim_id);

-- ---------------------------------------------------------------------------
-- Aggregates (on demand; reduction tree via parent_id)
-- ---------------------------------------------------------------------------

CREATE TABLE aggregate_summaries (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parent_id          bigint REFERENCES aggregate_summaries(id),  -- null = root of its tree
    query              jsonb NOT NULL,                  -- subjects, window, altitude, lens
    altitude           text NOT NULL CHECK (altitude IN ('ic', 'lead', 'manager', 'director', 'exec')),
    window_start       timestamptz NOT NULL,
    window_end         timestamptz NOT NULL,
    input_hash         text NOT NULL,                   -- cache key, see ADR-0008
    llm_call_id        bigint NOT NULL REFERENCES llm_calls(id),
    prompt_version_id  bigint NOT NULL REFERENCES prompt_versions(id),
    schema_version     integer NOT NULL,
    model_id           text NOT NULL,
    status             text NOT NULL CHECK (status IN ('published', 'low_coverage', 'needs_review', 'rejected')),
    headline           text NOT NULL,
    narrative          text NOT NULL,
    coverage           jsonb NOT NULL,                  -- {inputs, cited, uncited, ratio}
    created_at         timestamptz NOT NULL DEFAULT now(),
    requested_by_id    bigint REFERENCES people(id),
    CHECK (window_end > window_start)
);
CREATE INDEX aggregate_summaries_cache_idx ON aggregate_summaries (input_hash, prompt_version_id, schema_version, model_id);

-- Full input set of a (leaf) aggregate, so coverage is a join.
CREATE TABLE aggregate_inputs (
    aggregate_id   bigint NOT NULL REFERENCES aggregate_summaries(id) ON DELETE CASCADE,
    pr_summary_id  bigint NOT NULL REFERENCES pr_summaries(id),
    PRIMARY KEY (aggregate_id, pr_summary_id)
);

CREATE TABLE aggregate_claims (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    aggregate_id  bigint NOT NULL REFERENCES aggregate_summaries(id) ON DELETE CASCADE,
    ordinal       integer NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('feature', 'bugfix', 'refactor', 'infra', 'test', 'docs', 'perf', 'security', 'dependency', 'chore', 'other', 'theme')),
    text          text NOT NULL,
    UNIQUE (aggregate_id, ordinal)
);

-- The first-class provenance link for aggregates. Exactly one source column is set.
CREATE TABLE aggregate_claim_sources (
    id                        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    aggregate_claim_id        bigint NOT NULL REFERENCES aggregate_claims(id) ON DELETE CASCADE,
    pr_claim_id               bigint REFERENCES pr_claims(id),
    source_aggregate_claim_id bigint REFERENCES aggregate_claims(id),
    CHECK (num_nonnulls(pr_claim_id, source_aggregate_claim_id) = 1),
    UNIQUE (aggregate_claim_id, pr_claim_id),
    UNIQUE (aggregate_claim_id, source_aggregate_claim_id)
);
CREATE INDEX aggregate_claim_sources_pr_claim_idx  ON aggregate_claim_sources (pr_claim_id);
CREATE INDEX aggregate_claim_sources_agg_claim_idx ON aggregate_claim_sources (source_aggregate_claim_id);

-- ---------------------------------------------------------------------------
-- Verification and human feedback
-- ---------------------------------------------------------------------------

CREATE TABLE verifications (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pr_claim_id         bigint REFERENCES pr_claims(id) ON DELETE CASCADE,
    aggregate_claim_id  bigint REFERENCES aggregate_claims(id) ON DELETE CASCADE,
    llm_call_id         bigint NOT NULL REFERENCES llm_calls(id),
    verdict             text NOT NULL CHECK (verdict IN ('supported', 'partially_supported', 'unsupported', 'cannot_determine')),
    rationale           text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(pr_claim_id, aggregate_claim_id) = 1)
);

CREATE TABLE flags (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pr_claim_id         bigint REFERENCES pr_claims(id) ON DELETE CASCADE,
    aggregate_claim_id  bigint REFERENCES aggregate_claims(id) ON DELETE CASCADE,
    pr_summary_id       bigint REFERENCES pr_summaries(id) ON DELETE CASCADE,       -- whole-summary flags (e.g. omission)
    aggregate_id        bigint REFERENCES aggregate_summaries(id) ON DELETE CASCADE,
    raised_by_id        bigint NOT NULL REFERENCES people(id),
    category            text NOT NULL CHECK (category IN ('factual_error', 'overstated', 'understated', 'omission', 'misattribution', 'selective_emphasis', 'other')),
    comment             text NOT NULL DEFAULT '',
    status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'rejected', 'resolved')),  -- may be updated
    created_at          timestamptz NOT NULL DEFAULT now(),
    resolved_at         timestamptz,
    resolved_by_id      bigint REFERENCES people(id),
    CHECK (num_nonnulls(pr_claim_id, aggregate_claim_id, pr_summary_id, aggregate_id) = 1)
);
CREATE INDEX flags_open_idx ON flags (status) WHERE status = 'open';

-- ---------------------------------------------------------------------------
-- Background jobs and sync bookkeeping (Postgres-backed queue, SKIP LOCKED)
-- ---------------------------------------------------------------------------

CREATE TABLE jobs (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          text NOT NULL,                        -- ingest_repo, summarize_pr, verify_summary, aggregate
    payload       jsonb NOT NULL,
    status        text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'dead')),
    attempts      integer NOT NULL DEFAULT 0,
    max_attempts  integer NOT NULL DEFAULT 5,
    run_after     timestamptz NOT NULL DEFAULT now(),
    locked_at     timestamptz,
    last_error    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);
CREATE INDEX jobs_ready_idx ON jobs (run_after) WHERE status = 'queued';

CREATE TABLE sync_cursors (
    repository_id  bigint NOT NULL REFERENCES repositories(id),
    kind           text NOT NULL,                       -- pulls, teams, ...
    cursor         text,
    last_run_at    timestamptz,
    PRIMARY KEY (repository_id, kind)
);

CREATE TABLE audit_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id    bigint REFERENCES people(id),
    action      text NOT NULL,                          -- view_aggregate, raise_flag, resolve_flag, ...
    target      text NOT NULL,                          -- "aggregate:123"
    details     jsonb NOT NULL DEFAULT '{}',
    at          timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES ('0001_initial');
COMMIT;
