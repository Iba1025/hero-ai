"""RETRIEVE node — hybrid retrieval over manual corpus (spec §7).

Uses real retrieval pipeline when Qdrant client is provided;
falls back to stub evidence when no Qdrant is available (skeleton evals).
Fast path (complexity=="simple"): BM25-only top 5, no rerank.
Corrective loop is BL-9 (not in this phase).

P4-5 (INV-5): after evidence assembly BOTH paths run a verify-tier
sufficiency check; insufficient → sets pending_question and the existing
RETRIEVE→CLARIFY conditional routes to the interrupt. A triage "simple"
verdict must never let an insufficient ticket reach DIAGNOSE unasked —
insufficient fast-path tickets CLARIFY and loop back into the full path.
Runs at most once per ticket (never after a clarify round). Fails open —
a bad sufficiency call must never block a ticket.
"""

from __future__ import annotations

import logging
from typing import Any

from hero.graph.state import EvidenceChunk, TicketState
from hero.interfaces.embedder import Embedder
from hero.interfaces.reranker import Reranker
from hero.interfaces.vlm import VLM
from hero.safety.gate import clarify_allowed

logger = logging.getLogger(__name__)


def make_retrieve(
    embedder: Embedder,
    reranker: Reranker,
    qdrant_client: Any | None = None,
    fast_path: bool = False,
    vlm: VLM | None = None,
) -> Any:
    """Factory that returns a retrieve node with injected adapters.

    If qdrant_client is provided, uses real hybrid retrieval.
    Otherwise, produces stub evidence (for skeleton evals without Qdrant).
    fast_path=True builds the BL-4 fast-path node (BM25-only top 5, no
    rerank) — the TRIAGE conditional edge decides which node runs, so the
    node itself no longer reads state.complexity.
    vlm enables the P4-5 sufficiency check (both paths — INV-5: a triage
    "simple" verdict cannot skip it).
    """

    async def retrieve(state: dict[str, Any]) -> dict[str, Any]:
        description = state.get("description", "")

        # Real retrieval when Qdrant is available
        if qdrant_client is not None:
            from hero.retrieval.hybrid import retrieve_hybrid

            results = retrieve_hybrid(
                description,
                embedder=embedder,
                reranker=reranker,
                client=qdrant_client,
                fast_path=fast_path,
            )
            evidence = [c.model_dump() for c in results]
        else:
            # Stub fallback: fixed evidence chunks. Mirror the real paths'
            # retrieval_stage attribution (bm25/no-rerank vs fused+rerank).
            trade = state.get("trade", "other")
            candidates = [
                EvidenceChunk(
                    doc_id=f"manual-{trade}-001",
                    page=i,
                    score=0.9 - (i * 0.05),
                    retrieval_stage="bm25" if fast_path else "fused",
                )
                for i in range(1, 6)
            ]
            if not fast_path:
                candidates = reranker.rerank(description, candidates, top_k=5)
            evidence = [c.model_dump() for c in candidates]

        delta: dict[str, Any] = {"evidence": evidence}

        question = await _assess_sufficiency(state, evidence)
        if question:
            delta["pending_question"] = question
        return delta

    async def _assess_sufficiency(
        state: dict[str, Any], evidence: list[dict[str, Any]]
    ) -> str | None:
        """Return a clarify question, or None to proceed to DIAGNOSE."""
        if vlm is None:
            return None
        # Don't clobber an already-pending question (resume/injection paths),
        # and never re-check after ANY clarify round (P4-5 rider): the tenant
        # already answered once — re-asking is a UX anti-pattern and a latency
        # tax on exactly the slowest tickets. VERIFY + the safety gate still
        # gate the output; this also keeps the clarify cap unreachable
        # organically (injected rounds remain bounded by the cap in routing).
        if state.get("pending_question") or state.get("clarify_rounds", 0) >= 1:
            return None
        # Deterministic guardrail (P4-5b, INV-1): never CLARIFY on a hazard —
        # gas/HV/structural/water and hazard-keyword tickets go straight
        # through to the safety gate. No sufficiency tax paid on them either.
        if not clarify_allowed(trade=state.get("trade"), description=state.get("description", "")):
            return None
        try:
            ticket = TicketState(**{**state, "evidence": evidence})
            result = await vlm.assess_sufficiency(ticket)
        except Exception:
            # Fail open (P4-5): SufficiencyParseError (incl. generic-question
            # rejection) or any call failure proceeds to DIAGNOSE — VERIFY +
            # the safety gate still gate the output.
            logger.warning(
                "[RETRIEVE] sufficiency check failed — proceeding to DIAGNOSE (fail open)",
                exc_info=True,
            )
            return None
        if not result.sufficient and result.question:
            logger.info("[RETRIEVE] insufficient evidence — clarify question generated")
            return result.question
        return None

    return retrieve
