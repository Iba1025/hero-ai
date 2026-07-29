"""/health liveness probe (Phase 6, DEC-27) — shallow by design."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hero.api.main import create_app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://hero:hero@localhost:5432/hero")
    # No lifespan: /health must answer from the bare app — the probe is
    # process-liveness, not dependency health.
    return TestClient(create_app())


def test_health_returns_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
