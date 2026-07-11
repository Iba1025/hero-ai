"""VLM Protocol — spec §6.

The ONLY route to LLM providers (via LiteLLM adapter).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hero.graph.state import Hypothesis, TicketState


class DiagnosisParseError(Exception):
    """Raised when a diagnosis response cannot be parsed into hypotheses.

    The DIAGNOSE node escalates with reason `diagnosis_unparseable` —
    a placeholder fault must never be emitted (P3-1.5, baseline finding:
    the gpt-4o fallback produced 'Unknown fault' from unparseable JSON).
    """


@runtime_checkable
class VLM(Protocol):
    async def diagnose(self, state: TicketState) -> list[Hypothesis]:
        """Form fault hypotheses from ticket + evidence."""
        ...

    async def decompose_claims(self, hypothesis_text: str) -> list[str]:
        """Break a hypothesis into verifiable claims."""
        ...

    async def check_entailment(self, claim: str, evidence_text: str) -> bool:
        """Check if evidence entails the claim."""
        ...
