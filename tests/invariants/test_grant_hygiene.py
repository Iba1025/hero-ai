"""BL-42 — grant hygiene as invariant tests (Delivery Spec §8.1), real Postgres.

Postgres grants EXECUTE to PUBLIC by default on new functions, and granting to
a role is additive, not exclusive — so a forgotten REVOKE silently voids the
PRD §14 claim that `job_event`, `live_hazard_event`, and `dead_letter` are
append-only "enforced by grants, not convention". Those tables are the dispute
defence and the life-safety record.

These are tests, not migrations: the schema is built by running the REAL
alembic migrations into a scratch database, so a future migration that forgets
its REVOKEs fails CI the moment it lands. The append-only tables do not exist
yet (Phase 2/3); each check is enforced-if-present, so the failing test
arrives together with the forgetful migration, not before.

Deliberately not covered here: which role the API connects as at runtime.
Grants only bind if the runtime role is not the table owner — the role split
belongs to the migration that creates these tables (Phase 2), and this suite
will hold it to the grants half.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from tests.invariants.conftest import requires_docker

pytestmark = requires_docker

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRATCH_DB = "hero_grant_hygiene"

# PRD §14: append-only, enforced by grants (job ledger, life-safety record,
# failed-work record). Enforced-if-present — see module docstring.
APPEND_ONLY_TABLES = ("job_event", "live_hazard_event", "dead_letter")


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "+psycopg")


@pytest.fixture(scope="module")
def migrated_engine(postgres_url: str) -> Iterator[Engine]:
    """Run the real alembic migrations into a scratch DB; yield an engine on it."""
    admin = create_engine(_sync_url(postgres_url), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{_SCRATCH_DB}"'))
    admin.dispose()

    scratch_url = postgres_url.rsplit("/", 1)[0] + f"/{_SCRATCH_DB}"

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    # alembic/env.py reads DATABASE_URL and swaps in the sync driver itself.
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = scratch_url
    try:
        command.upgrade(cfg, "head")
    finally:
        if prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev

    engine = create_engine(_sync_url(scratch_url))
    yield engine
    engine.dispose()

    admin = create_engine(_sync_url(postgres_url), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}" WITH (FORCE)'))
    admin.dispose()


def test_migrations_reached_head(migrated_engine: Engine) -> None:
    """Sanity: the scratch DB really ran the migration chain (guards the fixture)."""
    with migrated_engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version == "0009"


def test_no_function_grants_execute_to_public(migrated_engine: Engine) -> None:
    """Every migration-created function must REVOKE EXECUTE FROM PUBLIC.

    acldefault() resolves proacl IS NULL to Postgres's default ACL, which
    includes EXECUTE for PUBLIC (grantee oid 0) — so an unadorned
    CREATE FUNCTION fails here, which is exactly the point.
    """
    with migrated_engine.connect() as conn:
        offenders = (
            conn.execute(
                text(
                    """
                SELECT p.oid::regprocedure::text
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(p.proacl, acldefault('f', p.proowner))
                ) AS acl
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND NOT EXISTS (      -- skip extension-owned functions
                      SELECT 1 FROM pg_depend d
                      WHERE d.objid = p.oid AND d.deptype = 'e'
                  )
                  AND acl.privilege_type = 'EXECUTE'
                  AND acl.grantee = 0   -- 0 = PUBLIC
                """
                )
            )
            .scalars()
            .all()
        )
    assert offenders == [], (
        f"Functions grant EXECUTE to PUBLIC (BL-42): {offenders}. "
        "Migrations creating functions must REVOKE ALL FROM PUBLIC and grant "
        "EXECUTE to the service role only."
    )


def test_every_function_pins_search_path(migrated_engine: Engine) -> None:
    """Every migration-created function must carry SET search_path = ...

    An unpinned search_path on a SECURITY DEFINER function is a privilege
    escalation; pinning all of them keeps the rule reviewable.
    """
    with migrated_engine.connect() as conn:
        offenders = (
            conn.execute(
                text(
                    """
                SELECT p.oid::regprocedure::text
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                  AND p.prokind = 'f'
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_depend d
                      WHERE d.objid = p.oid AND d.deptype = 'e'
                  )
                  AND (p.proconfig IS NULL OR NOT EXISTS (
                      SELECT 1 FROM unnest(p.proconfig) AS cfg
                      WHERE cfg LIKE 'search_path=%'
                  ))
                """
                )
            )
            .scalars()
            .all()
        )
    assert offenders == [], (
        f"Functions without a pinned search_path (BL-42): {offenders}. "
        "Add `SET search_path = public, pg_temp` (or stricter) in the migration."
    )


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_append_only_tables_revoke_update_and_delete(migrated_engine: Engine, table: str) -> None:
    """If an append-only table exists, no role but its owner may UPDATE/DELETE,
    and PUBLIC may hold nothing at all on it.

    Vacuous until the Phase 2/3 migrations create these tables — then the
    migration that creates one without its REVOKEs fails CI here.
    """
    with migrated_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"}
        ).scalar_one()
        if not exists:
            pytest.skip(f"{table} not migrated yet (Phase 2/3) — enforced when it lands")

        offenders = (
            conn.execute(
                text(
                    """
                SELECT acl.grantee::regrole::text || ':' || acl.privilege_type
                FROM pg_class c
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(c.relacl, acldefault('r', c.relowner))
                ) AS acl
                WHERE c.oid = to_regclass(:t)
                  AND (
                        (acl.privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
                         AND acl.grantee <> c.relowner)
                     OR acl.grantee = 0  -- PUBLIC holds nothing on these tables
                  )
                """
                ),
                {"t": f"public.{table}"},
            )
            .scalars()
            .all()
        )
    assert offenders == [], (
        f"{table} is append-only (PRD §14, INV-11) but carries grants: {offenders}. "
        "REVOKE UPDATE, DELETE, TRUNCATE — inserts only, and never via PUBLIC."
    )
