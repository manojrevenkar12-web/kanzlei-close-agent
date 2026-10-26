"""Session tokens: HMAC-signed, short-lived, carrying only the login. Rights are read from the
database on every request (db.principal), so revoking a person takes effect at once.

Production sign-in is the group's identity provider (OIDC) in front of this; the demo mode lets
anyone pick a demo person and is off by default.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def issue(login: str, secret: str, ttl_seconds: int = 8 * 3600) -> str:
    body = json.dumps({"sub": login, "exp": int(time.time()) + ttl_seconds}, separators=(",", ":")).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(body).decode().rstrip("=") + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")
    )


def verify(token: str, secret: str) -> str | None:
    try:
        b64_body, b64_sig = token.split(".", 1)
        body = base64.urlsafe_b64decode(b64_body + "=" * (-len(b64_body) % 4))
        sig = base64.urlsafe_b64decode(b64_sig + "=" * (-len(b64_sig) % 4))
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(sig, hmac.new(secret.encode(), body, hashlib.sha256).digest()):
        return None
    try:
        claims = json.loads(body)
    except json.JSONDecodeError:
        return None
    if int(claims.get("exp", 0)) < time.time():
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, str) else None
