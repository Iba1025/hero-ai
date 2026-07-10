"""Smoke test for LiteLLMVLM adapter — run locally with API keys.

NOT run in CI. Exercises the tiered model routing (DEC-18) and logs which
model served each call.

Usage:
    ANTHROPIC_API_KEY=... OPENAI_API_KEY=... uv run python scripts/smoke_vlm.py

Requires .env with API keys or environment variables set.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from hero.adapters.litellm_vlm import LiteLLMVLM
from hero.config import get_settings
from hero.graph.state import EvidenceChunk, TicketState

# Enable detailed logging so we see model routing
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")


async def main() -> int:
    settings = get_settings()

    vlm = LiteLLMVLM(
        primary_model=settings.vlm_model_primary,
        verify_model=settings.vlm_model_verify,
        fallback_model=settings.vlm_model_fallback,
    )

    print(f"\n{'=' * 60}")
    print("LiteLLMVLM Smoke Test (DEC-18 tiered routing)")
    print(f"  primary:  {settings.vlm_model_primary}")
    print(f"  verify:   {settings.vlm_model_verify}")
    print(f"  fallback: {settings.vlm_model_fallback}")
    print(f"{'=' * 60}\n")

    state = TicketState(
        ticket_id="smoke-001",
        description="Water leaking from under the kitchen sink. Puddle on floor.",
        trade="plumbing",
        evidence=[
            EvidenceChunk(
                doc_id="manual-plumbing-001",
                page=1,
                score=0.95,
                retrieval_stage="reranked",
            ),
        ],
    )

    # 1. DIAGNOSE — should use PRIMARY model
    print("--- 1. diagnose() [PRIMARY tier] ---")
    hypotheses = await vlm.diagnose(state)
    for h in hypotheses:
        print(f"  Fault: {h.fault}")
        print(f"  Claims: {len(h.claims)}")
        for c in h.claims:
            print(f"    - {c.text}")
        print(f"  calibrated_confidence: {h.calibrated_confidence} (must be None — INV-4)")
        assert h.calibrated_confidence is None, "INV-4 VIOLATION: model set confidence!"
    print()

    # 2. DECOMPOSE CLAIMS — should use VERIFY model
    print("--- 2. decompose_claims() [VERIFY tier] ---")
    claims = await vlm.decompose_claims(hypotheses[0].fault)
    for c in claims:
        print(f"  - {c}")
    print()

    # 3. CHECK ENTAILMENT — should use VERIFY model
    print("--- 3. check_entailment() [VERIFY tier] ---")
    result = await vlm.check_entailment(
        claim="The P-trap connection is leaking",
        evidence_text=(
            "Section 4.2: P-trap connections should be checked for corrosion and loose fittings."
        ),
    )
    print(f"  Entailment result: {result}")
    print()

    print(f"{'=' * 60}")
    print("Smoke test complete. Check logs above for model routing.")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
