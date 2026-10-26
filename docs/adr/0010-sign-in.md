# 10. Sign-in through the group's identity provider

Status: accepted

## Context
Staff already have accounts with the group's identity provider (typically Microsoft Entra ID). Clients
must reach the portal without any account.

## Decision
- The load balancer authenticates staff pages with OIDC. The portal (`/portal/*`, `/api/portal/*`),
  static files and the health check are excluded by a listener rule.
- The API trusts the load balancer's `x-amzn-oidc-data` header only after verifying its ES256
  signature with the regional public key, that the signer is our load balancer, and the expiry
  (`api/alb_oidc.py`, `tests/test_sso.py`). The e-mail claim must be a `staff.login`; rights come from
  the database on every request, so removing someone from `staff` takes effect at once.
- The API then issues its own short-lived session token (HMAC, 8 hours).
- The demo mode (a person picker) exists only with `KANZLEI_DEMO_MODE=true` and seeded data.
