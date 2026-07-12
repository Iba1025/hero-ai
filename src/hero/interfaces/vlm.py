"""VLM Protocol — spec §6.

The ONLY route to LLM providers (via LiteLLM adapter).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hero.graph.state import Hypothesis, SufficiencyResult, TicketState, TriageResult


class SufficiencyParseError(Exception):
    """Raised when a sufficiency response is unparseable OR its question is
    generic (P4-5). Recoverable: the RETRIEVE node fails open — proceeds to
    DIAGNOSE, where VERIFY + the safety gate still gate the output. A bad
    sufficiency call must never block a ticket, and a generic question
    ("please provide more details") must never reach a tenant.
    """


class TriageParseError(Exception):
    """Raised when a triage response cannot be parsed/validated (BL-4).

    Unlike DiagnosisParseError this is recoverable: the TRIAGE node falls
    back to the deterministic keyword classifier (full path) — a triage
    failure must never block a ticket or route it to the fast path.
    """


class DiagnosisParseError(Exception):
    """Raised when a diagnosis response cannot be parsed into hypotheses.

    The DIAGNOSE node escalates with reason `diagnosis_unparseable` —
    a placeholder fault must never be emitted (P3-1.5, baseline finding:
    the gpt-4o fallback produced 'Unknown fault' from unparseable JSON).
    """


@runtime_checkable
class VLM(Protocol):
    async def triage(self, description: str) -> TriageResult:
        """Classify trade + urgency + complexity (BL-4)."""
        ...

    async def diagnose(self, state: TicketState) -> list[Hypothesis]:
        """Form fault hypotheses from ticket + evidence."""
        ...

    async def decompose_claims(self, hypothesis_text: str) -> list[str]:
        """Break a hypothesis into verifiable claims."""
        ...

    async def check_entailment(self, claim: str, evidence_text: str) -> bool:
        """Check if evidence entails the claim."""
        ...

    async def assess_sufficiency(self, state: TicketState) -> SufficiencyResult:
        """Judge whether evidence + ticket support diagnosis (P4-5, INV-5).

        Insufficient → one concrete, tenant-answerable question.
        """
        ...
