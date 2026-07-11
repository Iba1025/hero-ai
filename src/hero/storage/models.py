"""SQLAlchemy models — full DDL per spec §5.

Migrations (Alembic) are the schema source of truth once created.
Media bytes never touch Postgres (INV-3) — object_key pointers only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    __tablename__ = "ticket"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    building_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    urgency: Mapped[str | None] = mapped_column(Text, nullable=True)
    trade: Mapped[str | None] = mapped_column(Text, nullable=True)
    complexity: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    media: Mapped[list[Media]] = relationship(back_populates="ticket")
    sensor_readings: Mapped[list[SensorReading]] = relationship(back_populates="ticket")
    diagnoses: Mapped[list[Diagnosis]] = relationship(back_populates="ticket")
    work_orders: Mapped[list[WorkOrder]] = relationship(back_populates="ticket")
    contractor_statements: Mapped[list[ContractorStatement]] = relationship(back_populates="ticket")


class Media(Base):
    """R2 pointer ONLY — no blob columns (INV-3)."""

    __tablename__ = "media"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ticket.id"), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    ticket: Mapped[Ticket] = relationship(back_populates="media")


class SensorReading(Base):
    """OPTIONAL enrichment (INV-7): table may be empty forever."""

    __tablename__ = "sensor_reading"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ticket.id"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Double, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="sensor_readings")


class Diagnosis(Base):
    __tablename__ = "diagnosis"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ticket.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    fault: Mapped[str] = mapped_column(Text, nullable=False)
    calibrated_confidence: Mapped[float | None] = mapped_column(Double, nullable=True)
    verify_pass: Mapped[bool] = mapped_column(Boolean, nullable=False)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    ticket: Mapped[Ticket] = relationship(back_populates="diagnoses")
    claims: Mapped[list[DiagnosisClaim]] = relationship(back_populates="diagnosis")
    contractor_statements: Mapped[list[ContractorStatement]] = relationship(
        back_populates="diagnosis"
    )


class DiagnosisClaim(Base):
    """DEC-6 audit trail — claim-level grounding."""

    __tablename__ = "diagnosis_claim"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    diagnosis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("diagnosis.id"), nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    # BL-6/DEC-19: which grounding threshold applied (part_number | descriptive)
    claim_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="descriptive")
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    diagnosis: Mapped[Diagnosis] = relationship(back_populates="claims")


class WorkOrder(Base):
    __tablename__ = "work_order"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ticket.id"), nullable=False)
    diagnosis_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("diagnosis.id"), nullable=True
    )
    sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    ticket: Mapped[Ticket] = relationship(back_populates="work_orders")


# Allowed contractor verdicts (BL-0). Kept next to the model so the DB CHECK,
# the API Literal, and this tuple cannot drift silently.
VALID_VERDICTS = ("confirmed", "partially_correct", "wrong")


class ContractorStatement(Base):
    """THE FLYWHEEL TABLE (BL-0).

    A ticket reaching 'resolved' without a row here is a bug (PRD §9).
    """

    __tablename__ = "contractor_statement"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ticket.id"), nullable=False)
    diagnosis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("diagnosis.id"), nullable=False
    )
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_fault: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_part_sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    contractor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unlabeled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        CheckConstraint(
            "verdict IS NOT NULL OR unlabeled_reason IS NOT NULL",
            name="verdict_or_reason",
        ),
        # P3-2: verdict vocabulary is closed — a free-text verdict is an unusable label.
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('confirmed', 'partially_correct', 'wrong')",
            name="verdict_allowed",
        ),
        # P3-2: a correction without the actual fault is not a training signal.
        CheckConstraint(
            "verdict IS NULL OR verdict = 'confirmed' OR actual_fault IS NOT NULL",
            name="correction_has_fault",
        ),
        Index("ix_contractor_statement_created_at", "created_at"),
    )

    ticket: Mapped[Ticket] = relationship(back_populates="contractor_statements")
    diagnosis: Mapped[Diagnosis] = relationship(back_populates="contractor_statements")
