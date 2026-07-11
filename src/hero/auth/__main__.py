"""CLI entry point: uv run python -m hero.auth seed --email ... --role ...

Admin user seeding (P4-1). There is no self-signup and no admin CRUD UI —
this CLI is the only way users are created.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hero.auth.passwords import hash_password
from hero.config import get_settings
from hero.storage.models import VALID_ROLES
from hero.storage.repo import create_user, get_user_by_email


async def _seed(*, email: str, password: str, role: str, org_id: uuid.UUID) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if await get_user_by_email(session, email) is not None:
                print(f"[SEED] user already exists: {email}", file=sys.stderr)
                return 1
            user = await create_user(
                session,
                org_id=org_id,
                email=email,
                password_hash=hash_password(password),
                role=role,
            )
            await session.commit()
            print(f"[SEED] created {role} {email} id={user.id} org_id={org_id}")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Hero.AI auth CLI")
    sub = parser.add_subparsers(dest="command")

    seed_p = sub.add_parser("seed", help="Create a user (admin seeding — no self-signup)")
    seed_p.add_argument("--email", required=True)
    seed_p.add_argument("--role", required=True, choices=list(VALID_ROLES))
    seed_p.add_argument(
        "--org-id",
        default=None,
        help="Org UUID. Omit to generate a new org id (printed) — use for the first user",
    )
    seed_p.add_argument(
        "--password",
        default=None,
        help="Omit to be prompted (recommended — keeps it out of shell history)",
    )

    args = parser.parse_args()
    if args.command != "seed":
        parser.print_help()
        return 1

    org_id = uuid.UUID(args.org_id) if args.org_id else uuid.uuid4()
    password = args.password or getpass.getpass("Password: ")
    if not password:
        print("[SEED] empty password refused", file=sys.stderr)
        return 1

    return asyncio.run(_seed(email=args.email, password=password, role=args.role, org_id=org_id))


if __name__ == "__main__":
    sys.exit(main())
