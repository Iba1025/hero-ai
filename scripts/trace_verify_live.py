"""BL-6 live verification trace — phase-close evidence for Phase 3 Step 1.

Runs ONE golden ticket (EVAL-001, simple_plumbing) through the full graph with
REAL adapters and prints the complete claim-level verification trace:
every claim, its type, the evidence text sent to entailment, the entailment
verdict, per-type grounding rates vs thresholds, and the resulting verify_pass.

Requires: API keys in .env, local Qdrant on QDRANT_URL (fixture is ingested
automatically if the collection is missing). Uses MemorySaver — this is a
one-shot local trace script, not a real run (INV-6 applies to real runs).
Local only — NEVER in CI.

Usage:
    QDRANT_URL=http://localhost:6333 uv run python scripts/trace_verify_live.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from qdrant_client import QdrantClient

from hero.adapters.platt import PlattCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.config import get_settings
from hero.graph.build import build_graph
from hero.ingestion.ingest import COLLECTION_NAME, ingest_pdf
from hero.verification.claims import gather_evidence_text

ROOT = Path(__file__).parent.parent
TICKET_PATH = ROOT / "evals" / "golden_tickets" / "simple_plumbing.json"
TEST_PDF = str(ROOT / "tests" / "fixtures" / "test_plumbing_manual.pdf")


class TracingVLM:
    """Wraps the real VLM and prints every entailment call + verdict."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.entailment_log: list[dict[str, Any]] = []

    async def diagnose(self, state: Any) -> Any:
        t0 = time.monotonic()
        result = await self._inner.diagnose(state)
        print(f"\n[DIAGNOSE] {len(result)} hypotheses in {time.monotonic() - t0:.2f}s")
        for h in result:
            print(f"  fault: {h.fault!r} ({len(h.claims)} claims)")
        return result

    async def decompose_claims(self, hypothesis_text: str) -> Any:
        return await self._inner.decompose_claims(hypothesis_text)

    async def check_entailment(self, claim: str, evidence_text: str) -> bool:
        t0 = time.monotonic()
        verdict = await self._inner.check_entailment(claim, evidence_text)
        elapsed = time.monotonic() - t0
        self.entailment_log.append({"claim": claim, "verdict": verdict, "elapsed_s": elapsed})
        print(f"  [ENTAILMENT] {elapsed:.2f}s verdict={verdict} claim={claim!r}")
        return verdict


def _ensure_ingested(client: QdrantClient, embedder: Any) -> None:
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in collections:
        print(f"[QDRANT] collection {COLLECTION_NAME!r} exists — reusing")
        return
    print(f"[QDRANT] ingesting fixture {TEST_PDF} with real embedder...")
    t0 = time.monotonic()
    count = ingest_pdf(
        pdf_path=TEST_PDF,
        doc_id="test-manual",
        manufacturer="ACME",
        model_codes=["PL-2000"],
        embedder=embedder,
        client=client,
    )
    print(f"[QDRANT] ingested {count} pages in {time.monotonic() - t0:.1f}s")


async def main() -> int:
    settings = get_settings()
    if not (settings.anthropic_api_key or settings.openai_api_key):
        raise SystemExit("Requires ANTHROPIC_API_KEY and/or OPENAI_API_KEY in .env")

    from hero.adapters.bge_reranker import BGEReranker
    from hero.adapters.colmodernvbert import ColModernVBertEmbedder
    from hero.adapters.litellm_vlm import LiteLLMVLM

    client = QdrantClient(url=settings.qdrant_url, timeout=30)
    client.get_collections()  # fail loudly if unreachable

    print("[LOAD] real adapters (ColModernVBERT + BGE + LiteLLMVLM)...")
    embedder = ColModernVBertEmbedder()
    reranker = BGEReranker()
    vlm = TracingVLM(
        LiteLLMVLM(
            primary_model=settings.vlm_model_primary,
            verify_model=settings.vlm_model_verify,
            fallback_model=settings.vlm_model_fallback,
        )
    )
    _ensure_ingested(client, embedder)

    graph = build_graph(
        embedder=embedder,
        reranker=reranker,
        calibrator=PlattCalibrator(),
        vlm=vlm,
        catalog=StubCatalogResolver(),
        checkpointer=MemorySaver(),
        grounding_threshold=settings.grounding_threshold,
        grounding_threshold_strict=settings.grounding_threshold_strict,
        qdrant_client=client,
    )

    ticket = json.loads(TICKET_PATH.read_text())
    print(f"\n{'=' * 70}")
    print(f"TICKET {ticket['ticket_id']}: {ticket['description']}")
    print(
        f"thresholds: descriptive>={settings.grounding_threshold} "
        f"part_number>={settings.grounding_threshold_strict}"
    )
    print(f"{'=' * 70}")

    config = {"configurable": {"thread_id": f"trace-verify-{ticket['ticket_id']}"}}
    result = await graph.ainvoke(
        {
            "ticket_id": ticket["ticket_id"],
            "description": ticket["description"],
            "media": [],
            "sensor_readings": [],  # INV-7: zero sensor data
        },
        config=config,
    )

    # --- Verification trace ---
    evidence = result.get("evidence", [])
    print(f"\n{'=' * 70}")
    print("VERIFICATION TRACE (BL-6 / DEC-6)")
    print(f"{'=' * 70}")
    print(f"\nEvidence sent to entailment ({len(evidence[:5])} chunks):")
    print(gather_evidence_text(evidence, max_chars_per_chunk=300))

    for hi, hyp in enumerate(result.get("hypotheses", [])):
        print(f"\nHYPOTHESIS {hi + 1}: {hyp.get('fault')!r}")
        conf = hyp.get("calibrated_confidence")
        print(f"  calibrated_confidence={conf} (Calibrator only, INV-4)")
        by_type: dict[str, list[int]] = {}
        for claim in hyp.get("claims", []):
            ctype = claim.get("claim_type")
            grounded = claim.get("grounded")
            g, n = by_type.get(ctype, [0, 0])
            by_type[ctype] = [g + int(bool(grounded)), n + 1]
            cites = [
                f"{e.get('doc_id')} p{e.get('page')}" for e in claim.get("supporting_evidence", [])
            ]
            print(f"  CLAIM: {claim.get('text')!r}")
            print(f"    type={ctype} grounded={grounded} evidence={cites or '[]'}")
        for ctype, (g, n) in sorted(by_type.items()):
            thr = (
                settings.grounding_threshold_strict
                if ctype == "part_number"
                else settings.grounding_threshold
            )
            print(
                f"  rate[{ctype}] = {g}/{n} = {g / n:.2f} (threshold {thr}) "
                f"-> {'PASS' if g / n >= thr else 'FAIL'}"
            )

    print(f"\nverify_pass = {result.get('verify_pass')}")
    print(f"escalated = {result.get('escalated')} ({result.get('escalation_reason')})")
    print(f"entailment calls = {len(vlm.entailment_log)} (all on VLM_MODEL_VERIFY tier)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
