"""The HTTP API as the web app and the client portal use it."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import login

pytestmark = pytest.mark.db
PERIOD = "2026-07"


def test_health_session_and_demo_people(client: Any) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}
    people = client.get("/api/demo-users").json()
    assert {p["role"] for p in people} == {"berater", "buchhaltung", "gruppe"}
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer forged.token"}).status_code == 401
    me = client.get("/api/me", headers=login(client, "c.hartmann")).json()
    assert me["can_sign_off"] and me["firm"]["chart"] == "SKR03"


def test_board_shows_only_the_persons_clients(client: Any) -> None:
    h = login(client, "j.wagner")
    rows = client.get(f"/api/closes?period={PERIOD}", headers=h).json()
    assert rows and all(r["id"].startswith("ys-") for r in rows)
    r = rows[0]
    assert r["transactions"] > 0 and r["items"] >= r["transactions"] and r["unprocessed"] == 0
    assert r["due_on"].startswith("2026-08") or r["due_on"].startswith("2026-09")
    assert client.get("/api/closes?period=2026-13", headers=h).status_code == 400


def test_group_engineer_sees_aggregates_not_clients(client: Any) -> None:
    h = login(client, "l.fde")
    assert client.get(f"/api/closes?period={PERIOD}", headers=h).status_code == 403
    roll = client.get(f"/api/rollout?period={PERIOD}", headers=h).json()
    assert {f["firm_id"] for f in roll["firms"]} == {"hartmann", "brandt", "yilmaz"}
    assert all(0 <= f["automation_share"] <= 1 for f in roll["firms"])
    assert client.get(f"/api/rollout?period={PERIOD}", headers=login(client, "s.akin")).status_code == 403


def test_item_detail_explains_itself(client: Any) -> None:
    h = login(client, "c.hartmann")
    data = client.get(f"/api/clients/hp-10101/periods/{PERIOD}/items", headers=h).json()
    assert data["chart"] == "SKR03" and data["items"]
    auto = next(i for i in data["items"] if i["state"] == "auto")
    d = client.get(f"/api/items/{auto['id']}", headers=h).json()
    assert d["reasons"] and d["final_lines"] and d["final_lines"][0]["debit_label"]
    assert client.get(f"/api/items/{auto['id']}", headers=login(client, "m.brandt")).status_code == 404


def test_review_correct_and_portal_answer(client: Any) -> None:
    h = login(client, "e.yilmaz")
    items = client.get(f"/api/clients/ys-30302/periods/{PERIOD}/items", headers=h).json()["items"]
    review = [i for i in items if i["state"] == "review"]
    if review:
        r = client.post(
            f"/api/items/{review[0]['id']}/correct",
            headers=h,
            json={"family": "office_supplies", "tax": "V19", "reason": "Test"},
        )
        assert r.status_code == 200 and r.json()["state"] == "done"
        assert client.post(f"/api/items/{review[0]['id']}/accept", headers=h).status_code == 409
    qs = client.get(f"/api/clients/ys-30302/periods/{PERIOD}/queries", headers=h).json()
    assert qs and "portal" in qs[0]["message"]


def test_portal_flow(client: Any, month_in_progress: dict[str, Any]) -> None:
    token = next(s["query"]["token"] for s in month_in_progress.values() if s.get("query"))
    b = client.get(f"/api/portal/{token}").json()
    assert b["items"] and b["firm"]
    first = b["items"][0]
    assert client.post(f"/api/portal/{token}/items/{first['item_id']}", json={"choice": "nonsense"}).status_code == 400
    choice = (
        next(o for o in first["options"] if o["value"] != "upload" and not o.get("needs"))["value"]
        if any(o["value"] != "upload" and not o.get("needs") for o in first["options"])
        else None
    )
    if choice:
        assert client.post(f"/api/portal/{token}/items/{first['item_id']}", json={"choice": choice}).status_code == 200
    assert client.get("/api/portal/short").status_code == 404


def test_vat_return_and_sign_off_rules(client: Any) -> None:
    h = login(client, "e.yilmaz")
    u = client.get(f"/api/clients/ys-30302/periods/{PERIOD}/ustva", headers=h).json()
    assert any(r["kz"] == "83" for r in u["rows"]) and "checks" in u and len(u["history"]) == 12
    acc = login(client, "j.wagner")
    r = client.post(f"/api/clients/ys-30302/periods/{PERIOD}/sign-off", headers=acc, json={"acknowledge_flags": True})
    assert r.status_code == 409


def test_account_mapping_is_for_group_and_advisors(client: Any) -> None:
    r = client.put("/api/firms/hartmann/accounts/4999", headers=login(client, "l.fde"), json={"family": "repairs"})
    assert r.status_code == 404  # no such unmapped account: nothing to map
    assert (
        client.put(
            "/api/firms/hartmann/accounts/4999", headers=login(client, "l.fde"), json={"family": "nonsense"}
        ).status_code
        == 400
    )


def test_audit_and_metrics(client: Any) -> None:
    a = client.get("/api/audit/verify", headers=login(client, "c.hartmann")).json()
    assert a["intact"] and a["checked"] > 0
    assert client.get("/api/audit/verify", headers=login(client, "t.voss")).status_code == 403
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/metrics", headers={"Authorization": "Bearer scrape"}).status_code == 200
