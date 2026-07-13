"""ticket.pipeline_status — background-pipeline progress (BL-17 / H1)

The graph now runs in a background task; POST intake/answer return immediately.
pipeline_status tracks the run itself, decoupled from the ticket lifecycle
`status`: queued → running → awaiting_tenant (CLARIFY interrupt) | complete |
failed.

Backfill: pre-async tickets ran synchronously — 'clarifying' means the run is
parked at CLARIFY (awaiting_tenant); every other non-open status means the run
finished (complete). 'open' rows never completed a run (queued).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "ticket",
        sa.Column("pipeline_status", sa.Text(), server_default="queued", nullable=False),
    )
    op.create_check_constraint(
        "pipeline_status_allowed",
        "ticket",
        "pipeline_status IN ('queued', 'running', 'awaiting_tenant', 'complete', 'failed')",
    )
    op.execute(
        "UPDATE ticket SET pipeline_status = CASE "
        "WHEN status = 'clarifying' THEN 'awaiting_tenant' "
        "WHEN status = 'open' THEN 'queued' "
        "ELSE 'complete' END"
    )


def downgrade() -> None:
    op.drop_constraint("pipeline_status_allowed", "ticket")
    op.drop_column("ticket", "pipeline_status")
