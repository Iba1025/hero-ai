"""CLI: create buildings and print tenant intake links (P4-4a).

    uv run python -m hero.buildings create --org-id <uuid> --name "12 Main St"
    uv run python -m hero.buildings list [--org-id <uuid>]

There is no building CRUD UI — this CLI is the only way building links are
minted. The slug is unguessable (secrets.token_urlsafe) and IS the tenant
credential: treat printed links accordingly.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hero.config import get_settings
from hero.storage.repo import create_building, list_buildings

_DEFAULT_BASE_URL = "http://localhost:5173"


def _intake_link(base_url: str, slug: str) -> str:
    return f"{base_url.rstrip('/')}/#/intake/{slug}"


async def _create(*, org_id: uuid.UUID, name: str, base_url: str) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            slug = secrets.token_urlsafe(24)
            building = await create_building(session, org_id=org_id, name=name, slug=slug)
            await session.commit()
            print(f"[BUILDING] created {name!r} id={building.id} org_id={org_id}")
            print(f"[BUILDING] tenant intake link: {_intake_link(base_url, slug)}")
            return 0
    finally:
        await engine.dispose()


async def _list(*, org_id: uuid.UUID | None, base_url: str) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            buildings = await list_buildings(session, org_id)
            if not buildings:
                print("[BUILDING] none found")
                return 0
            for b in buildings:
                print(f"{b.id}  org={b.org_id}  {b.name!r}  {_intake_link(base_url, b.slug)}")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Hero.AI building-link CLI (P4-4)")
    parser.add_argument(
        "--base-url",
        default=_DEFAULT_BASE_URL,
        help=f"SPA origin used in printed links (default {_DEFAULT_BASE_URL})",
    )
    sub = parser.add_subparsers(dest="command")

    create_p = sub.add_parser("create", help="Create a building and print its tenant link")
    create_p.add_argument("--org-id", required=True, help="Org UUID (same as your seeded users)")
    create_p.add_argument("--name", required=True, help="Display name shown to tenants")

    list_p = sub.add_parser("list", help="List buildings and their tenant links")
    list_p.add_argument("--org-id", default=None)

    args = parser.parse_args()
    if args.command == "create":
        return asyncio.run(
            _create(org_id=uuid.UUID(args.org_id), name=args.name, base_url=args.base_url)
        )
    if args.command == "list":
        org_id = uuid.UUID(args.org_id) if args.org_id else None
        return asyncio.run(_list(org_id=org_id, base_url=args.base_url))
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
