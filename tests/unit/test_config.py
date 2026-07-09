"""Tests for hero.config — region_guard() and Settings."""

from __future__ import annotations

import pytest

from hero.config import Settings, region_guard


def _make_settings(**overrides: str) -> Settings:
    defaults = {
        "database_url": "postgresql+asyncpg://hero:hero@localhost:5432/hero",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestRegionGuard:
    def test_localhost_always_allowed(self) -> None:
        s = _make_settings(database_url="postgresql+asyncpg://hero:hero@localhost:5432/hero")
        region_guard(s)  # should not raise

    def test_canadian_region_allowed(self) -> None:
        s = _make_settings(
            database_url="postgresql+asyncpg://hero:hero@db.ca-central-1.rds.amazonaws.com:5432/hero"
        )
        region_guard(s)  # should not raise

    def test_us_region_rejected(self) -> None:
        s = _make_settings(
            database_url="postgresql+asyncpg://hero:hero@db.us-east-1.rds.amazonaws.com:5432/hero"
        )
        with pytest.raises(RuntimeError, match="INV-2"):
            region_guard(s)

    def test_eu_region_rejected(self) -> None:
        s = _make_settings(
            database_url="postgresql+asyncpg://hero:hero@db.eu-west-1.rds.amazonaws.com:5432/hero"
        )
        with pytest.raises(RuntimeError, match="INV-2"):
            region_guard(s)

    def test_empty_values_skipped(self) -> None:
        s = _make_settings(qdrant_url="", langfuse_host="")
        region_guard(s)  # should not raise
