"""Stub VLM — deterministic fake for skeleton testing.

Returns fixed hypotheses with claims so the full pipeline can exercise
VERIFY and SAFETY_GATE without any real model call.
"""

from __future__ import annotations

from hero.graph.nodes.triage import keyword_triage
from hero.graph.state import Claim, EvidenceChunk, Hypothesis, TicketState, TriageResult


class StubVLM:
    """Deterministic VLM that returns a fixed hypothesis based on ticket trade."""

    async def triage(self, description: str) -> TriageResult:
        """Deterministic triage via the keyword classifier (BL-4)."""
        trade, urgency, complexity = keyword_triage(description)
        return TriageResult(trade=trade, urgency=urgency, complexity=complexity)

    async def diagnose(self, state: TicketState) -> list[Hypothesis]:
        trade = state.trade or "other"
        return [
            Hypothesis(
                fault=f"Stub diagnosis for {trade}: component failure",
                claims=[
                    Claim(
                        text=f"The {trade} system has a faulty component",
                        supporting_evidence=[
                            EvidenceChunk(
                                doc_id="stub-manual-001",
                                page=1,
                                score=0.95,
                                retrieval_stage="reranked",
                            )
                        ],
                    ),
                    Claim(
                        text="Replacement part is required",
                        supporting_evidence=[
                            EvidenceChunk(
                                doc_id="stub-manual-001",
                                page=2,
                                score=0.90,
                                retrieval_stage="reranked",
                            )
                        ],
                    ),
                ],
            )
        ]

    async def decompose_claims(self, hypothesis_text: str) -> list[str]:
        return [
            f"Claim derived from: {hypothesis_text}",
            "Replacement part is required",
        ]

    async def check_entailment(self, claim: str, evidence_text: str) -> bool:
        return True
