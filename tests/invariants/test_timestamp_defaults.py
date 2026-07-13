"""H4 / BL-20 — created_at defaults must be the now() FUNCTION, never a constant.

Postgres constant-folds ``DEFAULT 'now()'`` (string literal) to the timestamp
at DDL parse time — every row then carries the migration-run time instead of
its insert time. That broke ledger time coherence at the pilot rehearsal
(event 14:58 vs ticket 22:12) and silently defeated the rate-limit sliding
window. Two guards:

1. Live schema: pg_attrdef for every created_at column must be exactly now().
2. Source: no ``server_default="now()"`` string form in models or migrations.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.invariants.conftest import requires_docker

REPO_ROOT = Path(__file__).resolve().parents[2]


@requires_docker
@pytest.mark.asyncio
async def test_created_at_defaults_are_the_now_function(db_session: AsyncSession) -> None:
    rows = (
        await db_session.execute(
            text(
                """
                SELECT c.relname AS tbl, pg_get_expr(d.adbin, d.adrelid) AS default_expr
                FROM pg_attrdef d
                JOIN pg_class c ON c.oid = d.adrelid
                JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE a.attname = 'created_at' AND n.nspname = current_schema()
                """
            )
        )
    ).all()
    assert rows, "expected created_at columns in the schema"
    frozen = {tbl: expr for tbl, expr in rows if expr != "now()"}
    assert not frozen, f"created_at defaults folded to constants: {frozen}"


def test_no_string_now_defaults_in_source() -> None:
    """The string form is the bug — only sa.text('now()') evaluates per-insert."""
    offenders: list[str] = []
    for path in [
        *(REPO_ROOT / "alembic" / "versions").glob("*.py"),
        REPO_ROOT / "src" / "hero" / "storage" / "models.py",
    ]:
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if 'server_default="now()"' in line or "server_default='now()'" in line:
                offenders.append(f"{path.name}:{lineno}")
    # Migrations 0004/0005/0006/0008 keep the historical (buggy) DDL on
    # purpose — 0009 corrects it. Only NEW occurrences are failures.
    known_historical = {"0004_", "0005_", "0006_", "0008_"}
    new = [o for o in offenders if not any(o.startswith(p) for p in known_historical)]
    assert not new, f"string 'now()' server_default (folds to a constant): {new}"
