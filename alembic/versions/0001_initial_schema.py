"""initial schema — full DDL per spec §5

Revision ID: 0001
Revises:
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # -- ticket
    op.create_table(
        "ticket",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("building_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("urgency", sa.Text(), nullable=True),
        sa.Column("trade", sa.Text(), nullable=True),
        sa.Column("complexity", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # -- media (INV-3: object_key pointer ONLY, no blob columns)
    op.create_table(
        "media",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("ticket.id"), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # -- sensor_reading (INV-7: OPTIONAL enrichment, table may be empty forever)
    op.create_table(
        "sensor_reading",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("ticket.id"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )

    # -- diagnosis
    op.create_table(
        "diagnosis",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("ticket.id"), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("fault", sa.Text(), nullable=False),
        sa.Column("calibrated_confidence", sa.Double(), nullable=True),
        sa.Column("verify_pass", sa.Boolean(), nullable=False),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # -- diagnosis_claim (DEC-6 audit trail)
    op.create_table(
        "diagnosis_claim",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("diagnosis_id", sa.Uuid(), sa.ForeignKey("diagnosis.id"), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
    )

    # -- work_order
    op.create_table(
        "work_order",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("ticket.id"), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), sa.ForeignKey("diagnosis.id"), nullable=True),
        sa.Column("sku", sa.Text(), nullable=True),
        sa.Column("body", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # -- contractor_statement (THE FLYWHEEL TABLE — BL-0, PRD §9)
    op.create_table(
        "contractor_statement",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("ticket.id"), nullable=False),
        sa.Column("diagnosis_id", sa.Uuid(), sa.ForeignKey("diagnosis.id"), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("actual_fault", sa.Text(), nullable=True),
        sa.Column("actual_part_sku", sa.Text(), nullable=True),
        sa.Column("contractor_id", sa.Uuid(), nullable=True),
        sa.Column("free_text", sa.Text(), nullable=True),
        sa.Column("unlabeled_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "verdict IS NOT NULL OR unlabeled_reason IS NOT NULL",
            name="verdict_or_reason",
        ),
    )
    op.create_index(
        "ix_contractor_statement_created_at",
        "contractor_statement",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_contractor_statement_created_at", table_name="contractor_statement")
    op.drop_table("contractor_statement")
    op.drop_table("work_order")
    op.drop_table("diagnosis_claim")
    op.drop_table("diagnosis")
    op.drop_table("sensor_reading")
    op.drop_table("media")
    op.drop_table("ticket")
