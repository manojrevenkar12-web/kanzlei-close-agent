# Working in this repository

Fast feedback:

- `cd backend && ruff check src tests && ruff format --check src tests && mypy && pytest -q`. The db
  tests need PostgreSQL: `KANZLEI_TEST_ADMIN_URL`, default `postgresql://postgres:postgres@localhost:5432/postgres`.
- `cd web && npm run lint && npm run typecheck && npm test`.
- `python -m kanzlei_sim evaluate --sets dev,v1,v2 && python -m kanzlei_sim gate` (about ten minutes),
  then `python -m kanzlei_sim seed --reset --links .demo-links.json`, the API, `npm run preview` and
  `npx playwright test` with `E2E_LINKS`.

Invariants (each has a test):

- Models read, rules decide tax: learning parts return a family; the tax code comes from
  `domain/tax.py`, the account from the chart (`tests/test_rules.py`).
- Rights are enforced by Postgres. Request code runs in `as_user`; simulation, training and evaluation
  in `as_system`. The group role sees aggregates only; the portal goes through security-definer
  functions keyed by a token hash (`tests/test_db.py`, `tests/test_api.py`).
- A signed-off month cannot change; events are append-only and hash-chained (`tests/test_db.py`).
- The product package `kanzlei` never imports `kanzlei_sim` and never reads the truth
  (`tests/test_isolation.py`).
- A model sees no IBAN, e-mail, phone or tax id, only for firms with a § 62a agreement date, and its
  invoice reading must add up (`tests/test_isolation.py`).
- Thresholds, vocabulary, charts and tax constants live in `config/`, not in code.
- The web app uses theme tokens only; every query shows loading, error with retry, and empty states.

Held-out rule: never change the engine, rules, classifier or decision model to do better on a blind set
under `backend/src/kanzlei_sim/blind/`. A set is committed before it runs; its first run
`reports/blind/<set>/FIRST_RUN.json` is never rewritten (CI checks). If you study a set's failures,
write `regression` to its `STATUS` file and have someone who has not seen the code write a new set
from `blind/WRITING_CASES.md` only.
