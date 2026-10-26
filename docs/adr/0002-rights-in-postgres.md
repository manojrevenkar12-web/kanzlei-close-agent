# 2. Rights and tenancy are enforced by Postgres

Status: accepted

## Context
The group buys tax firms. Each firm's clients are confidential to that firm (§ 57 StBerG, § 203 StGB),
and inside a firm a bookkeeper works on assigned clients. The group's own engineers need to see how
the rollout goes across firms, but not client data.

## Decision
- Row-level security on every client table, forced also for the table owner. The app connects as
  `kanzlei_app` (`NOBYPASSRLS`); each request sets `app.login` in its transaction (`db.as_user`).
- `app_client_visible(client_id)` is the one rule: `buchhaltung` sees assigned clients, `berater`
  all clients of their firm, `gruppe` none.
- The group sees aggregates through security-definer functions `rollout()` and
  `rollout_periods()` that return numbers per firm only.
- The client portal has no account: `portal_bundle(token)` and `portal_answer(...)` are
  security-definer functions keyed by the SHA-256 of a random token. The token is never stored.
- Simulation, training and evaluation run as system (`as_system`), never in request code.

## Consequences
- A missing `WHERE` in a query cannot leak another firm's clients; tests check rights at the
  database level (`tests/test_db.py`) and through the API (`tests/test_api.py`).
- The rollout view cannot show client names even if the frontend asked for them.
