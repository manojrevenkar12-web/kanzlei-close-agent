"""Fixtures. `db` tests need PostgreSQL: KANZLEI_TEST_ADMIN_URL (default: local postgres)."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from kanzlei.config import Settings, close_config, config_dir
from kanzlei.db import Pool, as_system, as_user, create_pool, principal
from kanzlei.engine.classifier import Classifier
from kanzlei.engine.close import Engine
from kanzlei.engine.decision import DecisionModel
from kanzlei.migrate import migrate
from kanzlei.onboarding import import_package
from kanzlei.storage import LocalStore
from kanzlei_sim import render
from kanzlei_sim.run import build_package, opening_for
from kanzlei_sim.world import DEV, HISTORY, build

ADMIN = os.environ.get("KANZLEI_TEST_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
DB = "kanzlei_test"
PERIOD = DEV[0]


def _url(base: str, db: str, user: str | None = None, password: str | None = None) -> str:
    from urllib.parse import urlsplit, urlunsplit

    u = urlsplit(base)
    netloc = u.netloc
    if user:
        netloc = f"{user}:{password}@{netloc.split('@')[-1]}"
    return urlunsplit((u.scheme, netloc, f"/{db}", u.query, u.fragment))


@pytest.fixture(scope="session")
def world() -> list[Any]:
    return build()


@pytest.fixture(scope="session")
def database(world: list[Any]) -> Iterator[dict[str, str]]:
    try:
        with psycopg.connect(ADMIN, autocommit=True, connect_timeout=3) as c:
            c.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
            c.execute(f"CREATE DATABASE {DB}")
    except psycopg.OperationalError as e:  # pragma: no cover
        pytest.skip(f"no PostgreSQL for db tests: {e}")
    admin = _url(ADMIN, DB)
    app = _url(ADMIN, DB, "kanzlei_app", "kanzlei_app")
    migrate(admin, "kanzlei_app")
    pool = create_pool(app, 2)
    root = Path(tempfile.mkdtemp(prefix="kca-test-"))
    for f in world:
        build_package(f, root / f.id, HISTORY)
        with as_system(pool) as conn:
            import_package(conn, root / f.id, actor="test")
    pool.close()
    yield {"admin": admin, "app": app, "root": str(root)}


@pytest.fixture(scope="session")
def pool(database: dict[str, str]) -> Iterator[Pool]:
    p = create_pool(database["app"], 6)
    yield p
    p.close()


@pytest.fixture(scope="session")
def engine(database: dict[str, str]) -> Engine:
    return Engine(
        LocalStore(Path(database["root"]) / "documents"),
        Classifier.load(),
        DecisionModel.load(config_dir() / close_config().decision_model_file),
    )


@pytest.fixture(scope="session")
def month_in_progress(pool: Pool, engine: Engine, world: list[Any]) -> dict[str, Any]:
    """July 2026 imported and run for every client (nothing reviewed yet)."""
    out: dict[str, Any] = {}
    for f in world:
        for c in f.clients:
            who = principal(pool, c.assigned[0])
            assert who is not None
            with as_user(pool, who) as conn:
                xml, _ = render.camt053(c, PERIOD, c.months[PERIOD], opening_for(c, PERIOD))
                engine.import_statement(conn, c.id, xml, "camt.xml", who)
                for e in c.months[PERIOD]:
                    if e.document and e.document.arrives == "with_statement":
                        name, data = render.document(c, c.party(e.party), e.document)
                        engine.import_document(
                            conn, c.id, data, name, source="upload", direction=e.document.direction, actor=who
                        )
                out[c.id] = engine.run(conn, c.id, PERIOD, who)
    return out


@pytest.fixture(scope="session")
def client(pool: Pool, engine: Engine, database: dict[str, str], month_in_progress: dict[str, Any]):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from kanzlei.api.app import Deps, build_app

    s = Settings(
        database_url=database["app"],
        admin_database_url=database["admin"],
        token_secret="test-secret",
        demo_mode=True,
        metrics_token="scrape",
    )
    return TestClient(build_app(Deps(pool=pool, settings=s, engine=engine, store=engine.store)))


def login(client: Any, who: str) -> dict[str, str]:
    r = client.post("/api/session", json={"login": who})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
