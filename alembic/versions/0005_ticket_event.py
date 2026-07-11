"""ticket_event table — P4-3 ledger journal (append-only pipeline audit trail)

One row per pipeline state that actually ran, written by the API layer after
graph runs. seq orders entries within a ticket. Claim substance stays in
diagnosis_claim (DEC-6) — the ledger endpoint joins it by run_id.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_event",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default="now()", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["ticket_id"], ["ticket.id"]),
    )
    op.create_index("ix_ticket_event_ticket_seq", "ticket_event", ["ticket_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_ticket_event_ticket_seq", table_name="ticket_event")
    op.drop_table("ticket_event")
