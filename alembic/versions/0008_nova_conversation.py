"""conversation_message + rate_limit_event — Nova chat state (Phase 5 STEP 3)

conversation_message: the Nova chat transcript (DEC-23), one append-only row
per message, ordered by seq within a ticket. Guardrail outcomes (DEC-24) are
recorded per row (kind + guardrail_reason); chat-tier cost per model reply.

rate_limit_event: Postgres-backed sliding-window rate limiting (BL-15) —
replaces the in-memory per-process limiter, so counts survive restarts and
are shared across workers.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_message",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), server_default="chat", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("guardrail_reason", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Double(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default="now()", nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["ticket.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("sender IN ('tenant', 'nova')", name="conversation_sender_allowed"),
        sa.CheckConstraint(
            "kind IN ('chat', 'redirect', 'capped', 'escalation', "
            "'clarify_question', 'clarify_answer', 'completion')",
            name="conversation_kind_allowed",
        ),
    )
    op.create_index(
        "ix_conversation_message_ticket_seq", "conversation_message", ["ticket_id", "seq"]
    )

    op.create_table(
        "rate_limit_event",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default="now()", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rate_limit_event_key_created_at", "rate_limit_event", ["key", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_event_key_created_at", table_name="rate_limit_event")
    op.drop_table("rate_limit_event")
    op.drop_index("ix_conversation_message_ticket_seq", table_name="conversation_message")
    op.drop_table("conversation_message")
