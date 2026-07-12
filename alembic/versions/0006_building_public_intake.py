"""building table + public tenant intake columns — P4-4

- building: org-scoped rows whose unguessable slug is the tenant link
  (no tenant accounts; created only via `python -m hero.buildings create`).
- ticket.tenant_contact: phone or email for the CLARIFY loop.
- ticket.public_slug: unguessable per-ticket status-link slug (NULL for
  operator-created tickets).
- media.sha256 -> nullable: public tenants on non-HTTPS LAN phones have no
  crypto.subtle, so the client-side hash is best-effort.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "building",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default="now()", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_building_org_id", "building", ["org_id"])
    op.add_column("ticket", sa.Column("tenant_contact", sa.Text(), nullable=True))
    op.add_column("ticket", sa.Column("public_slug", sa.Text(), nullable=True))
    op.create_index("ix_ticket_public_slug", "ticket", ["public_slug"], unique=True)
    op.alter_column("media", "sha256", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("media", "sha256", existing_type=sa.Text(), nullable=False)
    op.drop_index("ix_ticket_public_slug", table_name="ticket")
    op.drop_column("ticket", "public_slug")
    op.drop_column("ticket", "tenant_contact")
    op.drop_index("ix_building_org_id", table_name="building")
    op.drop_table("building")
