"""Sign-in through the load balancer's OIDC header: only a token our load balancer signed counts."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from kanzlei.api.alb_oidc import AlbIdentity

ARN = "arn:aws:elasticloadbalancing:eu-central-1:111122223333:loadbalancer/app/kanzlei/abc"
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER = ec.generate_private_key(ec.SECP256R1())


def _pem(k: ec.EllipticCurvePrivateKey) -> bytes:
    return k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def _b64(b: bytes, pad: bool) -> str:
    s = base64.urlsafe_b64encode(b).decode()
    return s if pad else s.rstrip("=")


def token(
    claims: dict[str, Any],
    *,
    key: ec.EllipticCurvePrivateKey = KEY,
    signer: str = ARN,
    kid: str = "k1",
    pad: bool = True,
) -> str:
    h = _b64(json.dumps({"alg": "ES256", "kid": kid, "signer": signer, "typ": "JWT"}).encode(), pad)
    p = _b64(json.dumps(claims).encode(), pad)
    der = key.sign(f"{h}.{p}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return f"{h}.{p}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'), pad)}"


def identity() -> tuple[AlbIdentity, list[str]]:
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return _pem(KEY)

    return AlbIdentity("eu-central-1", ARN, fetch), fetched


def good(**over: Any) -> dict[str, Any]:
    return {"email": "C.Hartmann@hartmann-partner.de", "exp": int(time.time()) + 120, **over}


def test_valid_token_names_the_person_and_caches_the_key() -> None:
    idp, fetched = identity()
    assert idp.login(token(good())) == "c.hartmann@hartmann-partner.de"
    assert idp.login(token(good(), pad=False)) == "c.hartmann@hartmann-partner.de"
    assert fetched == ["https://public-keys.auth.elb.eu-central-1.amazonaws.com/k1"]


@pytest.mark.parametrize(
    "bad",
    [
        token(good(), key=OTHER),  # signed by someone else
        token(good(), signer=ARN.replace("abc", "evil")),  # another load balancer
        token(good(exp=int(time.time()) - 3600)),  # expired
        token(good(email="no-email-claim")),
        token(good(), kid="../../etc/passwd"),
        "not.a.token",
        "",
        None,
    ],
)
def test_anything_else_is_refused(bad: str | None) -> None:
    idp, _ = identity()
    assert idp.login(bad) is None


def test_tampered_claims_fail_the_signature() -> None:
    idp, _ = identity()
    h, _, s = token(good()).split(".")
    forged = base64.urlsafe_b64encode(json.dumps(good(email="m.brandt@brandt.de")).encode()).decode()
    assert idp.login(f"{h}.{forged}.{s}") is None


@pytest.mark.db
def test_api_signs_in_through_the_identity_provider_only(pool, engine, database, month_in_progress) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from kanzlei.api.app import Deps, build_app
    from kanzlei.config import Settings

    idp, _ = identity()
    s = Settings(database_url=database["app"], admin_database_url=database["admin"], token_secret="t", demo_mode=False)
    c = TestClient(build_app(Deps(pool=pool, settings=s, engine=engine, store=engine.store, identity=idp)))
    assert c.get("/api/sign-in").json() == {"mode": "sso"}
    assert c.get("/api/demo-users").status_code == 404
    # The demo picker is off: naming a login gets nobody in.
    assert c.post("/api/session", json={"login": "c.hartmann"}).status_code == 401
    # A verified identity that is not on the staff list gets no session.
    stranger = token(good(email="someone@else.de"))
    assert c.post("/api/session", json={}, headers={"x-amzn-oidc-data": stranger}).status_code == 403
    # In production staff.login is the e-mail address the identity provider sends.
    from kanzlei.db import as_system

    with as_system(pool) as conn:
        conn.execute(
            "INSERT INTO staff (login, firm_id, name, role) SELECT 'claudia@hartmann.example', firm_id, name, role FROM staff WHERE login = 'c.hartmann' ON CONFLICT DO NOTHING"
        )
    r = c.post("/api/session", json={}, headers={"x-amzn-oidc-data": token(good(email="Claudia@Hartmann.example"))})
    assert r.status_code == 200
    me = c.get("/api/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).json()
    assert me["role"] == "berater" and me["firm"]["name"].startswith("Steuerkanzlei Hartmann")
