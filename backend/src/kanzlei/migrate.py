"""Applies migrations in order, once, under an advisory lock (safe with several replicas)."""

from __future__ import annotations

from importlib import resources

import psycopg
from psycopg import sql


def migrate(admin_url: str, app_password: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(515151)")
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, at timestamptz DEFAULT now())"
            )
            done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
            files = sorted(
                (f for f in resources.files("kanzlei.migrations").iterdir() if f.name.endswith(".sql")),
                key=lambda f: f.name,
            )
            for f in files:
                if f.name in done:
                    continue
                with conn.transaction():
                    conn.execute(f.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
                applied.append(f.name)
            conn.execute(sql.SQL("ALTER ROLE kanzlei_app PASSWORD {}").format(sql.Literal(app_password)))
        finally:
            conn.execute("SELECT pg_advisory_unlock(515151)")
    return applied
