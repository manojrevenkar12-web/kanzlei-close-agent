"""Connections. Every unit of work runs as a staff member (row-level security) or as the system."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

Conn = psycopg.Connection[DictRow]
Pool = ConnectionPool[Conn]


@dataclass(frozen=True)
class Principal:
    login: str
    name: str
    role: str  # buchhaltung | berater | gruppe
    firm_id: str | None

    @property
    def can_sign_off(self) -> bool:
        return self.role == "berater"

    @property
    def group(self) -> bool:
        return self.role == "gruppe"


SYSTEM = Principal("system", "System", "system", None)


def create_pool(url: str, size: int = 10) -> Pool:
    pool: Pool = ConnectionPool(url, min_size=1, max_size=size, kwargs={"row_factory": dict_row}, open=True)
    pool.wait()
    return pool


@contextmanager
def as_user(pool: Pool, p: Principal, *, rollback: bool = False) -> Iterator[Conn]:
    """A transaction in which Postgres shows only what this person may see.

    The setting is transaction-local (set_config(..., true)), so a pooled connection never carries
    one person's rights into the next request.
    """
    if p.login == "system":
        with as_system(pool, rollback=rollback) as conn:
            yield conn
        return
    with pool.connection() as conn, conn.transaction(force_rollback=rollback):
        conn.execute("SELECT set_config('app.login', %s, true)", (p.login,))
        yield conn


@contextmanager
def as_system(pool: Pool, *, rollback: bool = False) -> Iterator[Conn]:
    with pool.connection() as conn, conn.transaction(force_rollback=rollback):
        conn.execute("SELECT set_config('app.system', 'on', true)")
        yield conn


def principal(pool: Pool, login: str) -> Principal | None:
    """Rights come from the staff table, never from the token."""
    with as_system(pool) as conn:
        row = conn.execute("SELECT login, name, role, firm_id FROM staff WHERE login = %s", (login,)).fetchone()
    if not row:
        return None
    return Principal(row["login"], row["name"], row["role"], row["firm_id"])


def event(
    conn: Conn, actor: str, kind: str, payload: dict[str, Any], *, firm: str | None = None, client: str | None = None
) -> None:
    conn.execute(
        "SELECT append_event(%s, %s, %s, %s, %s::jsonb)", (actor, firm, client, kind, json.dumps(payload, default=str))
    )
