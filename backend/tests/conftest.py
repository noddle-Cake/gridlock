"""Shared test fixtures.

DB-backed tests need a disposable Postgres+PostGIS database. Start one with
`docker compose up -d testdb` and set
TEST_DATABASE_URL=postgresql://gridmerge:gridmerge@localhost:5433/gridmerge_test
(that URL is the default). They are skipped when no database is reachable.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest
from hypothesis import HealthCheck, settings

from app.services.geocoding import Candidate

settings.register_profile(
    "gridmerge", max_examples=100, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
settings.load_profile("gridmerge")

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://gridmerge:gridmerge@localhost:5433/gridmerge_test"
)


def _db_available() -> bool:
    import asyncpg

    async def probe() -> bool:
        try:
            conn = await asyncpg.connect(TEST_DATABASE_URL, timeout=3)
        except Exception:
            return False
        await conn.close()
        return True

    return asyncio.run(probe())


DB_AVAILABLE = _db_available()
requires_db = pytest.mark.skipif(
    not DB_AVAILABLE, reason=f"no Postgres+PostGIS test database at {TEST_DATABASE_URL}"
)


_RESET_SQL = """
DELETE FROM briefs; DELETE FROM projects; DELETE FROM plans;
ALTER SEQUENCE projects_id_seq RESTART;
"""
_schema_applied = False


async def reset_db(conn) -> None:
    global _schema_applied
    if not _schema_applied:
        from app.db.pool import SCHEMA_PATH

        await conn.execute(SCHEMA_PATH.read_text())
        _schema_applied = True
    await conn.execute(_RESET_SQL)


_runner: asyncio.Runner | None = None
_conn = None


def run_db(fn):
    """Run `await fn(conn)` against a freshly reset test database.

    One long-lived loop + connection serves every call, so a 100-example
    property test does not pay connection setup 100 times.
    """
    import asyncpg

    global _runner, _conn
    if _runner is None:
        _runner = asyncio.Runner()
    if _conn is None or _conn.is_closed():
        _conn = _runner.run(asyncpg.connect(TEST_DATABASE_URL))

    async def main():
        await reset_db(_conn)
        return await fn(_conn)

    return _runner.run(main())


class FakeLLM:
    """LLM stand-in: returns canned JSON/text, or raises / sleeps on demand."""

    def __init__(
        self, projects: list[dict[str, Any]] | None = None, brief: str | None = None,
        fail: bool = False, delay: float = 0.0,
    ) -> None:
        self.projects = projects or []
        self.brief = brief
        self.fail = fail
        self.delay = delay
        self.prompts: list[str] = []

    async def generate_json(self, prompt: str, schema: dict[str, Any]) -> str:
        self.prompts.append(prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("model unavailable")
        return json.dumps({"projects": self.projects})

    async def generate_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("model unavailable")
        return self.brief or "We propose sharing a crane crew across both sites."


class FakeGeocoder:
    """Resolves names from a fixed table; unknown names return no candidates."""

    def __init__(self, table: dict[str, list[Candidate]] | None = None) -> None:
        self.table = table or {}
        self.calls: list[str] = []

    async def resolve(self, name: str) -> list[Candidate]:
        self.calls.append(name)
        return self.table.get(name, [])


@pytest.fixture
def api_client():
    """A TestClient wired to the test DB, a FakeLLM, and a FakeGeocoder."""
    if not DB_AVAILABLE:
        pytest.skip(f"no Postgres+PostGIS test database at {TEST_DATABASE_URL}")
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import create_app

    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    get_settings.cache_clear()
    run_db(lambda conn: asyncio.sleep(0))  # reset schema + data

    llm = FakeLLM()
    geocoder = FakeGeocoder()
    app = create_app(llm=llm, geocoder=geocoder)
    with TestClient(app) as client:
        client.llm = llm  # type: ignore[attr-defined]
        client.geocoder = geocoder  # type: ignore[attr-defined]
        client.app_state = app.state  # type: ignore[attr-defined]
        yield client
    get_settings.cache_clear()
