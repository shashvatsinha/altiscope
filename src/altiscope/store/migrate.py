"""Apply numbered SQL migrations in order.

Migration files retain their historical ``BEGIN``/``COMMIT`` wrappers. The runner
inserts the version record immediately before the final ``COMMIT`` so the schema
change and its bookkeeping are committed atomically. The first migration records
itself too; ``ON CONFLICT DO NOTHING`` makes the runner's record compatible with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import LiteralString, cast

import psycopg
from psycopg import sql

_BEGIN_RE = re.compile(r"(?im)^[ \t]*BEGIN[ \t]*;[ \t]*(?:--[^\n]*)?$")
_COMMIT_RE = re.compile(r"(?im)^[ \t]*COMMIT[ \t]*;[ \t]*(?:--[^\n]*)?$")


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path


def discover(migrations_dir: Path) -> list[Migration]:
    files = sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    return [Migration(version=f.stem, path=f) for f in files]


def applied_versions(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('schema_migrations') IS NOT NULL")
        row = cur.fetchone()
        if row is None or not row[0]:
            return set()
        cur.execute("SELECT version FROM schema_migrations")
        # A SQL_ASCII database hands text back as bytes; normalise so comparisons hold.
        return {
            r[0].decode("utf-8") if isinstance(r[0], bytes) else str(r[0]) for r in cur.fetchall()
        }


def _atomic_query(migration: Migration) -> sql.Composed:
    migration_sql = migration.path.read_text(encoding="utf-8")
    begins = list(_BEGIN_RE.finditer(migration_sql))
    commits = list(_COMMIT_RE.finditer(migration_sql))
    if len(begins) != 1 or len(commits) != 1 or begins[0].start() > commits[0].start():
        raise ValueError(
            f"migration {migration.path} must contain exactly one BEGIN and one later COMMIT"
        )

    commit = commits[0]
    return (
        sql.SQL(cast(LiteralString, migration_sql[: commit.start()]))
        + sql.SQL(
            "INSERT INTO schema_migrations (version) VALUES ({}) ON CONFLICT DO NOTHING;\n"
        ).format(sql.Literal(migration.version))
        + sql.SQL(cast(LiteralString, migration_sql[commit.start() :]))
    )


def apply_pending(conn: psycopg.Connection, migrations_dir: Path) -> list[str]:
    done = applied_versions(conn)
    pending = [migration for migration in discover(migrations_dir) if migration.version not in done]
    if not pending:
        return []

    # End the read transaction opened by applied_versions so every file's BEGIN starts
    # a distinct transaction. This matches the runner's existing connection-owning API.
    conn.commit()
    applied: list[str] = []
    for migration in pending:
        try:
            with conn.cursor() as cur:
                cur.execute(_atomic_query(migration))
        except Exception:
            conn.rollback()
            raise
        applied.append(migration.version)
    return applied
