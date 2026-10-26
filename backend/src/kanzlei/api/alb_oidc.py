"""Production sign-in: the load balancer authenticates people against the group's identity provider
(OIDC, e.g. Microsoft Entra ID) and passes the signed claims in `x-amzn-oidc-data`. The API trusts
that header only after checking its ES256 signature with the load balancer's public key and that the
signer is our load balancer; then the e-mail claim names the staff member (`staff.login`).

Rights still come from the database on every request, so removing a person from `staff` takes
effect at once even while the identity provider still knows them.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import load_pem_public_key

HEADER = "x-amzn-oidc-data"


def _b64(s: str) -> bytes:
    # The load balancer pads with "=" although JWTs normally do not; accept both.
    s = s.strip().rstrip("=")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=5) as r:
        body: bytes = r.read()
        return body


class AlbIdentity:
    def __init__(self, region: str, alb_arn: str, fetch: Callable[[str], bytes] = _fetch, leeway: int = 60) -> None:
        self.region = region
        self.alb_arn = alb_arn
        self.fetch = fetch
        self.leeway = leeway
        self._keys: dict[str, ec.EllipticCurvePublicKey] = {}

    def _key(self, kid: str) -> ec.EllipticCurvePublicKey:
        if kid not in self._keys:
            if not kid or "/" in kid or ".." in kid:
                raise ValueError("bad key id")
            pem = self.fetch(f"https://public-keys.auth.elb.{self.region}.amazonaws.com/{kid}")
            key = load_pem_public_key(pem)
            if not isinstance(key, ec.EllipticCurvePublicKey):
                raise ValueError("not an EC key")
            self._keys[kid] = key
        return self._keys[kid]

    def claims(self, token: str | None) -> dict[str, Any] | None:
        """The verified claims, or None for anything that is not a valid token from our load balancer."""
        if not token:
            return None
        try:
            h64, p64, s64 = token.split(".")
            header = json.loads(_b64(h64))
            if header.get("alg") != "ES256" or header.get("signer") != self.alb_arn:
                return None
            sig = _b64(s64)
            if len(sig) != 64:
                return None
            der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
            self._key(str(header.get("kid", ""))).verify(der, f"{h64}.{p64}".encode(), ec.ECDSA(hashes.SHA256()))
            claims: dict[str, Any] = json.loads(_b64(p64))
        except (ValueError, InvalidSignature, json.JSONDecodeError, OSError):
            return None
        if int(claims.get("exp", 0)) + self.leeway < time.time():
            return None
        return claims

    def login(self, token: str | None) -> str | None:
        c = self.claims(token)
        email = c.get("email") if c else None
        return email.strip().lower() if isinstance(email, str) and "@" in email else None
