"""contractor_statement label-quality constraints — BL-0 flywheel hardening (P3-2)

verdict_allowed: verdict vocabulary is closed (confirmed|partially_correct|wrong) —
a free-text verdict is an unusable label.
correction_has_fault: a correction (partially_correct|wrong) must carry actual_fault —
otherwise it is not a training signal.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "verdict_allowed",
        "contractor_statement",
        "verdict IS NULL OR verdict IN ('confirmed', 'partially_correct', 'wrong')",
    )
    op.create_check_constraint(
        "correction_has_fault",
        "contractor_statement",
        "verdict IS NULL OR verdict = 'confirmed' OR actual_fault IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("correction_has_fault", "contractor_statement", type_="check")
    op.drop_constraint("verdict_allowed", "contractor_statement", type_="check")
