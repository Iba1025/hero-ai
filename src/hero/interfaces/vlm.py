"""VLM Protocol — spec §6.

The ONLY route to LLM providers (via LiteLLM adapter).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hero.graph.state import Hypothesis, TicketState


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
