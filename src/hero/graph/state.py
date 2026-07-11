"""TicketState — single typed state object per spec §4.

Nodes take and return TicketState deltas.

GraphState (TypedDict) is used for LangGraph's StateGraph definition.
TicketState (Pydantic) is used for validation within nodes.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

TradeCategory = Literal[
    "hvac",
    "plumbing",
    "electrical",
    "appliance",
    "structural",
    "water_intrusion",
    "gas",
    "other",
]
Complexity = Literal["simple", "standard", "complex"]


Urgency = Literal["emergency", "urgent", "routine"]


class TriageResult(BaseModel):
    """VLM triage output (BL-4). Pydantic validation IS the parse gate —
    an out-of-vocabulary trade/urgency/complexity fails validation and the
    TRIAGE node falls back to the deterministic keyword classifier."""

    trade: TradeCategory
    urgency: Urgency
    complexity: Complexity


class MediaRef(BaseModel):
    """R2 key — POINTER ONLY (INV-3)."""

    object_key: str
    media_type: Literal["image", "video"]
    sha256: str


class SensorReading(BaseModel):
    """OPTIONAL enrichment only (INV-7)."""

    source: str
    metric: str
    value: float
    unit: str
    observed_at: str  # ISO 8601


class EvidenceChunk(BaseModel):
    doc_id: str  # manual document id
    page: int
    region: dict[str, object] | None = None  # bbox; BL-7, nullable until then
    score: float  # post-rerank score
    retrieval_stage: Literal["dense", "bm25", "fused", "reranked"]
    text: str | None = None  # page text from Qdrant payload — reranker/VERIFY input


class Claim(BaseModel):
    """DEC-6: claim-level verification."""

    text: str
    grounded: bool | None = None
    claim_type: Literal["part_number", "descriptive"] | None = None  # set by VERIFY (BL-6)
    supporting_evidence: list[EvidenceChunk] = Field(default_factory=list)


class Hypothesis(BaseModel):
    fault: str
    claims: list[Claim]
    # World-knowledge inferences / recommended next steps from DIAGNOSE.
    # Carried for the contractor; VERIFY does NOT gate on these (P3-1.5).
    reasoning: list[str] = Field(default_factory=list)
    # NOTE: no `model_confidence` field, ever (INV-4).
    calibrated_confidence: float | None = None  # set only by Calibrator


class TicketState(BaseModel):
    ticket_id: str
    description: str
    media: list[MediaRef] = Field(default_factory=list)
    sensor_readings: list[SensorReading] = Field(default_factory=list)  # INV-7: may be empty

    # TRIAGE
    urgency: Urgency | None = None
    trade: TradeCategory | None = None
    complexity: Complexity | None = None  # BL-4

    # RETRIEVE
    evidence: list[EvidenceChunk] = Field(default_factory=list)
    corrective_rounds: int = 0
    clarify_rounds: int = 0  # cap at 3, then escalate to human dispatcher
    pending_question: str | None = None  # set by CLARIFY; graph interrupts here

    # DIAGNOSE / VERIFY
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    verify_pass: bool | None = None  # per-claim grounding rate >= threshold

    # SAFETY_GATE
    escalated: bool = False
    escalation_reason: str | None = None

    # RESOLVE / PROCURE
    work_order_id: str | None = None
    sku: str | None = None


class GraphState(TypedDict, total=False):
    """TypedDict version of TicketState for LangGraph's StateGraph.

    LangGraph uses TypedDict annotations to track/merge state across nodes.
    """

    ticket_id: str
    description: str
    media: list[dict[str, object]]
    sensor_readings: list[dict[str, object]]
    urgency: str | None
    trade: str | None
    complexity: str | None
    evidence: list[dict[str, object]]
    corrective_rounds: int
    clarify_rounds: int
    pending_question: str | None
    hypotheses: list[dict[str, object]]
    verify_pass: bool | None
    escalated: bool
    escalation_reason: str | None
    work_order_id: str | None
    sku: str | None
