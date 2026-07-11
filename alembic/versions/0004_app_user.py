"""app_user table — P4-1 auth (email+password, argon2id, roles, org scoping)

No self-signup: rows are seeded via `python -m hero.auth seed`.
role_allowed: closed vocabulary (operator|contractor|admin).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default="now()", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.CheckConstraint("role IN ('operator', 'contractor', 'admin')", name="role_allowed"),
    )
    op.create_index("ix_app_user_org_id", "app_user", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_app_user_org_id", table_name="app_user")
    op.drop_table("app_user")
