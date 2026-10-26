"""The database guarantees: who sees what, what cannot change, what the protocol shows."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from kanzlei.db import Pool, as_system, as_user, principal
from kanzlei.engine.close import CloseError, Engine
from kanzlei.formats.extf import read_buchungsstapel

pytestmark = pytest.mark.db
PERIOD = "2026-07"


def who(pool: Pool, login: str) -> Any:
    p = principal(pool, login)
    assert p is not None
    return p


def visible_clients(pool: Pool, login: str) -> set[str]:
    with as_user(pool, who(pool, login)) as conn:
        return {r["id"] for r in conn.execute("SELECT id FROM clients").fetchall()}


def test_rights_follow_role_and_assignment(pool: Pool, month_in_progress: dict[str, Any]) -> None:
    with as_system(pool) as conn:
        assigned = {
            r["client_id"] for r in conn.execute("SELECT client_id FROM assignments WHERE login = 't.voss'").fetchall()
        }
        hartmann = {r["id"] for r in conn.execute("SELECT id FROM clients WHERE firm_id = 'hartmann'").fetchall()}
    assert visible_clients(pool, "t.voss") == assigned and assigned < hartmann
    assert visible_clients(pool, "c.hartmann") == hartmann
    assert visible_clients(pool, "l.fde") == set()  # the group sees no client data
    with as_user(pool, who(pool, "m.brandt")) as conn:  # another firm's tax advisor
        assert not (hartmann & {r["id"] for r in conn.execute("SELECT id FROM clients").fetchall()})
        assert (
            conn.execute("SELECT count(*) AS n FROM bookings WHERE client_id = ANY(%s)", (list(hartmann),)).fetchone()[
                "n"
            ]
            == 0
        )  # type: ignore[index]
        assert (
            conn.execute("SELECT count(*) AS n FROM documents WHERE client_id = ANY(%s)", (list(hartmann),)).fetchone()[
                "n"
            ]
            == 0
        )  # type: ignore[index]


def test_no_writes_into_other_clients(pool: Pool, month_in_progress: dict[str, Any]) -> None:
    with as_user(pool, who(pool, "m.brandt")) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "INSERT INTO bookings (client_id, period, booking_date, amount_cents, debit, credit, tax, origin) VALUES ('hp-10101', '2026-07', '2026-07-01', 100, 4930, 1200, 'V19', 'manual')"
        )


def test_history_and_protocol_cannot_change(pool: Pool, month_in_progress: dict[str, Any]) -> None:
    with as_system(pool) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE bookings SET amount_cents = amount_cents + 1 WHERE id = (SELECT id FROM bookings WHERE locked LIMIT 1)"
        )
    # The app role has no right to delete from the protocol, and a trigger stops even the owner.
    with as_system(pool) as conn, pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)):
        conn.execute("DELETE FROM events WHERE id = (SELECT min(id) FROM events)")
    with as_system(pool) as conn:
        r = conn.execute("SELECT * FROM verify_events()").fetchone()
    assert r is not None and r["first_broken"] is None and r["checked"] > 10


def test_portal_token_reaches_one_bundle_only(pool: Pool, month_in_progress: dict[str, Any]) -> None:
    from kanzlei.storage import sha256

    tokens = [s["query"]["token"] for s in month_in_progress.values() if s.get("query")]
    assert len(tokens) >= 2
    with as_system(pool) as conn:
        rows = conn.execute(
            "SELECT DISTINCT query_id, client_name FROM portal_bundle(%s)", (sha256(tokens[0].encode()),)
        ).fetchall()
        assert len(rows) == 1
        assert conn.execute("SELECT count(*) AS n FROM portal_bundle(%s)", (sha256(b"guess"),)).fetchone()["n"] == 0  # type: ignore[index]
    # The application role cannot read queries without a person or the system set.
    with pool.connection() as conn, conn.transaction():
        assert conn.execute("SELECT count(*) AS n FROM queries").fetchone()["n"] == 0  # type: ignore[index]
        assert conn.execute("SELECT count(*) AS n FROM bookings").fetchone()["n"] == 0  # type: ignore[index]


def test_close_review_sign_off_and_lock(pool: Pool, engine: Engine, month_in_progress: dict[str, Any]) -> None:
    client_id = "hp-10102"
    acc, berater = who(pool, "t.voss"), who(pool, "c.hartmann")
    if client_id not in visible_clients(pool, "t.voss"):
        acc = who(pool, "n.krause")
    with as_user(pool, acc) as conn:
        with pytest.raises(CloseError, match="Steuerberater"):
            engine.sign_off(conn, client_id, PERIOD, acc, acknowledge_flags=True)
        for it in conn.execute(
            "SELECT id, state, kind FROM items WHERE client_id = %s AND period = %s AND state IN ('review', 'client')",
            (client_id, PERIOD),
        ).fetchall():
            if it["state"] == "review":
                engine.accept(conn, it["id"], acc)
            else:
                engine.park(conn, it["id"], acc, "Test")
        checks = engine.checks(conn, client_id, PERIOD)
        assert checks["bank_reconciled"] and not checks["open_review"] and not checks["open_client"]
    with as_user(pool, berater) as conn:
        out = engine.sign_off(conn, client_id, PERIOD, berater, acknowledge_flags=True)
        assert len(out["sha256"]) == 64
    with as_user(pool, berater) as conn:
        _name, data = engine.export(conn, client_id, PERIOD)
        header, rows = read_buchungsstapel(data)
        assert header.locked and header.chart == "03" and rows
        total = conn.execute(
            "SELECT count(*) AS n FROM bookings WHERE client_id = %s AND period = %s", (client_id, PERIOD)
        ).fetchone()["n"]  # type: ignore[index]
        assert len(rows) == total
    with as_user(pool, berater) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE bookings SET text = 'x' WHERE client_id = %s AND period = %s", (client_id, PERIOD))
    with as_user(pool, acc) as conn, pytest.raises(CloseError, match="festgeschrieben"):
        engine.run(conn, client_id, PERIOD, acc)


def test_onboarding_reports_mapping_coverage(pool: Pool, month_in_progress: dict[str, Any]) -> None:
    with as_system(pool) as conn:
        rows = conn.execute("SELECT client_id, summary FROM imports WHERE kind = 'buchungsstapel'").fetchall()
    assert len(rows) == 9
    assert all(r["summary"]["volume_mapped_share"] > 0.95 for r in rows)
