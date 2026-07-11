"""diagnosis_claim.claim_type — BL-6 claim classifier audit trail (DEC-19)

The claim type records which grounding threshold was applied per claim
(part_number → GROUNDING_THRESHOLD_STRICT, descriptive → GROUNDING_THRESHOLD).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "diagnosis_claim",
        sa.Column("claim_type", sa.Text(), nullable=False, server_default="descriptive"),
    )


def downgrade() -> None:
    op.drop_column("diagnosis_claim", "claim_type")
