"""Apply numbered SQL migrations in order. Each file is one transaction.

The first migration creates schema_migrations itself; the runner tolerates that by
recording versions with ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psycopg


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path


def discover(migrations_dir: Path) -> list[Migration]:
    files = sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    return [Migration(version=f.stem, path=f) for f in files]


def applied_versions(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
        row = cur.fetchone()
        if row is None or not row[0]:
            return set()
        cur.execute("SELECT version FROM schema_migrations")
        # A SQL_ASCII database hands text back as bytes; normalise so comparisons hold.
        return {
            r[0].decode("utf-8") if isinstance(r[0], bytes) else str(r[0]) for r in cur.fetchall()
        }


def apply_pending(conn: psycopg.Connection, migrations_dir: Path) -> list[str]:
    done = applied_versions(conn)
    applied: list[str] = []
    for m in discover(migrations_dir):
        if m.version in done:
            continue
        sql = m.path.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql)  # type: ignore[arg-type]
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
                (m.version,),
            )
        conn.commit()
        applied.append(m.version)
    return applied
