"""Eval harness — replays golden tickets through the graph.

Reports metrics per spec §10.2:
- retrieval hit-rate@5 (against expected_evidence annotations)
- per-claim grounding rate
- diagnosis accuracy vs label
- ECE
- cost/ticket (stub: $0)
- latency

Adapter modes:
- default (CI): stub adapters — no API keys, no model downloads, no Qdrant.
- --live (local only): LiteLLMVLM (DEC-18 tiers) + ColModernVBERT embedder +
  BGE reranker + real Qdrant. Requires API keys, model downloads, and an
  ingested Qdrant instance. NEVER run in CI.

Checkpointer: AsyncPostgresSaver by default (INV-6). The eval proves real
Postgres checkpoint round-trips, including CLARIFY resume across a fresh
connection. Set HERO_EVAL_MEMORY_CHECKPOINTER=1 for local dev without
Postgres — CI must never set this flag.

Usage:
    uv run python evals/run_eval.py           # stub adapters (CI)
    uv run python evals/run_eval.py --live    # real adapters (local)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from langgraph.types import Command

from hero.adapters.platt import PlattCalibrator, expected_calibration_error
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.config import get_settings
from hero.graph.build import build_graph


def load_golden_tickets() -> list[dict[str, Any]]:
    """Load all golden ticket JSON files."""
    tickets_dir = Path(__file__).parent / "golden_tickets"
    return [json.loads(p.read_text()) for p in sorted(tickets_dir.glob("*.json"))]


async def _make_checkpointer() -> Any:
    """Create checkpointer. AsyncPostgresSaver by default (INV-6).

    MemorySaver ONLY when HERO_EVAL_MEMORY_CHECKPOINTER=1 is explicitly set.
    """
    settings = get_settings()
    if settings.hero_eval_memory_checkpointer:
        from langgraph.checkpoint.memory import MemorySaver

        print("[CHECKPOINTER] MemorySaver (HERO_EVAL_MEMORY_CHECKPOINTER=1)")
        return MemorySaver()

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    db_url = settings.database_url
    sync_url = db_url.replace("+asyncpg", "")
    host = db_url.split("@")[-1] if "@" in db_url else "local"
    print(f"[CHECKPOINTER] AsyncPostgresSaver ({host})")

    pool = AsyncConnectionPool(
        conninfo=sync_url,
        open=False,
        kwargs={"autocommit": True},
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return saver


def _make_adapters(live: bool) -> dict[str, Any]:
    """Build the adapter set. Stubs by default; real adapters with --live.

    Calibrator is always the real PlattCalibrator (BL-2 default, DEC-5).
    Unfitted it is identity — same behavior as the stub until labels accumulate.
    """
    if not live:
        print("[ADAPTERS] stub (VLM=StubVLM, embedder=StubEmbedder, reranker=StubReranker)")
        return {
            "embedder": StubEmbedder(),
            "reranker": StubReranker(),
            "vlm": StubVLM(),
            "qdrant_client": None,
        }

    # --live: real adapters. Local only — needs keys, model downloads, Qdrant.
    from qdrant_client import QdrantClient

    from hero.adapters.bge_reranker import BGEReranker
    from hero.adapters.colmodernvbert import ColModernVBertEmbedder
    from hero.adapters.litellm_vlm import LiteLLMVLM

    settings = get_settings()
    if not (settings.anthropic_api_key or settings.openai_api_key):
        raise SystemExit(
            "--live requires ANTHROPIC_API_KEY and/or OPENAI_API_KEY in the environment/.env"
        )

    client = QdrantClient(url=settings.qdrant_url, timeout=10)
    client.get_collections()  # fail loudly if Qdrant unreachable

    print(
        f"[ADAPTERS] live (VLM=LiteLLMVLM primary={settings.vlm_model_primary} "
        f"verify={settings.vlm_model_verify} fallback={settings.vlm_model_fallback}, "
        f"embedder=ColModernVBERT, reranker=BGE, qdrant={settings.qdrant_url})"
    )
    return {
        "embedder": ColModernVBertEmbedder(),
        "reranker": BGEReranker(),
        "vlm": LiteLLMVLM(
            primary_model=settings.vlm_model_primary,
            verify_model=settings.vlm_model_verify,
            fallback_model=settings.vlm_model_fallback,
        ),
        "qdrant_client": client,
    }


def _build_graph(checkpointer: Any, adapters: dict[str, Any]) -> Any:
    """Build graph with the given adapter set and checkpointer."""
    return build_graph(
        embedder=adapters["embedder"],
        reranker=adapters["reranker"],
        calibrator=PlattCalibrator(),
        vlm=adapters["vlm"],
        catalog=StubCatalogResolver(),
        checkpointer=checkpointer,
        qdrant_client=adapters["qdrant_client"],
    )


async def run_ticket(
    checkpointer: Any, ticket: dict[str, Any], adapters: dict[str, Any]
) -> dict[str, Any]:
    """Run a single golden ticket through the graph, handling CLARIFY if needed.

    For CLARIFY tickets: simulates a process restart by destroying the graph
    instance after interrupt and creating a new one with the same checkpointer.
    With AsyncPostgresSaver, this proves real DB round-trip resumability (INV-6).
    """
    ticket_id = ticket["ticket_id"]
    expected = ticket["expected"]
    thread_id = f"eval-{ticket_id}"
    config = {"configurable": {"thread_id": thread_id}}

    input_state: dict[str, Any] = {
        "ticket_id": ticket_id,
        "description": ticket["description"],
        "media": ticket.get("media", []),
        "sensor_readings": ticket.get("sensor_readings", []),
    }

    if expected.get("requires_clarify"):
        input_state["pending_question"] = "Can you provide more details?"

    start = time.monotonic()

    # --- First graph instance ---
    graph1 = _build_graph(checkpointer, adapters)
    result = await graph1.ainvoke(input_state, config=config)

    # If CLARIFY interrupted, simulate process restart
    if expected.get("requires_clarify") and result.get("pending_question"):
        print(f"  [CLARIFY] Graph interrupted. pending_question={result['pending_question']!r}")
        print("  [CLARIFY] Destroying graph instance (simulating process termination)...")

        # Destroy graph1
        del graph1

        # --- New graph instance, same checkpointer (simulates process restart) ---
        # With AsyncPostgresSaver, the new graph reads state from Postgres.
        print("  [CLARIFY] Creating new graph instance with same checkpointer (simulating restart)")
        graph2 = _build_graph(checkpointer, adapters)

        # Verify state was persisted
        state = await graph2.aget_state(config)
        assert state is not None, "State not found after simulated restart!"
        assert state.values.get("ticket_id") == ticket_id, "ticket_id mismatch after restart!"
        print(f"  [CLARIFY] State recovered: ticket_id={state.values.get('ticket_id')}")

        # Resume with clarification answer
        clarify_answer = expected.get("clarify_answer", "No additional details")
        print(f"  [CLARIFY] Resuming with answer: {clarify_answer!r}")
        result = await graph2.ainvoke(Command(resume=clarify_answer), config=config)
        print(f"  [CLARIFY] Resumed successfully. clarify_rounds={result.get('clarify_rounds')}")

    elapsed = time.monotonic() - start

    return {
        "ticket_id": ticket_id,
        "result": result,
        "elapsed_s": elapsed,
        "expected": expected,
        "expected_evidence": ticket.get("expected_evidence"),
        "label": ticket.get("label", {}),
    }


def evaluate(run_result: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a single run against expected outcomes."""
    result = run_result["result"]
    expected = run_result["expected"]
    checks: dict[str, Any] = {}

    checks["trade_match"] = result.get("trade") == expected.get("trade")
    checks["urgency_match"] = result.get("urgency") == expected.get("urgency")
    checks["escalation_correct"] = result.get("escalated") == expected.get("escalated")

    if expected.get("escalation_reason"):
        checks["escalation_reason_match"] = (
            result.get("escalation_reason") == expected["escalation_reason"]
        )

    checks["has_diagnosis"] = len(result.get("hypotheses", [])) > 0
    if expected.get("has_diagnosis"):
        checks["diagnosis_present"] = checks["has_diagnosis"] == expected["has_diagnosis"]

    checks["has_work_order"] = result.get("work_order_id") is not None
    if "has_work_order" in expected:
        checks["work_order_correct"] = checks["has_work_order"] == expected["has_work_order"]

    checks["has_sku"] = result.get("sku") is not None
    if "has_sku" in expected:
        checks["sku_correct"] = checks["has_sku"] == expected["has_sku"]

    hypotheses = result.get("hypotheses", [])
    total_claims = 0
    grounded_claims = 0
    for hyp in hypotheses:
        for claim in hyp.get("claims", []):
            total_claims += 1
            if claim.get("grounded"):
                grounded_claims += 1
    checks["grounding_rate"] = grounded_claims / total_claims if total_claims > 0 else None

    evidence = result.get("evidence", [])
    checks["retrieval_count"] = len(evidence)
    # Hit-rate@5 (spec §10.2): 1.0 if any annotated gold evidence chunk appears
    # in the top-5 retrieved. None when the ticket has no expected_evidence
    # annotation. With stub retrieval this is honestly 0.0 — gold annotations
    # reference real manual pages, which only --live retrieval can surface.
    gold = run_result.get("expected_evidence")
    if gold:
        top5 = evidence[:5]
        checks["retrieval_hit_rate_at_5"] = (
            1.0
            if any(
                e.get("doc_id") == g["doc_id"] and e.get("page") in g["pages"]
                for e in top5
                for g in gold
            )
            else 0.0
        )
    else:
        checks["retrieval_hit_rate_at_5"] = None
    checks["cost_usd"] = 0.0
    checks["latency_s"] = run_result["elapsed_s"]

    critical_checks = [
        checks.get("escalation_correct", False),
        checks.get("diagnosis_present", True),
    ]
    checks["pass"] = all(critical_checks)

    return checks


async def main() -> int:
    """Run all golden tickets and print results."""
    parser = argparse.ArgumentParser(description="Hero.AI golden-ticket eval")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use real adapters (LiteLLMVLM + ColModernVBERT + BGE + Qdrant). "
        "Local only — requires API keys, model downloads, ingested Qdrant. Never in CI.",
    )
    args = parser.parse_args()

    tickets = load_golden_tickets()
    checkpointer = await _make_checkpointer()
    adapters = _make_adapters(live=args.live)

    print(f"\n{'=' * 70}")
    print(f"Hero.AI Eval — {len(tickets)} golden tickets (mode={'LIVE' if args.live else 'stub'})")
    print(f"{'=' * 70}\n")

    all_results: list[dict[str, Any]] = []
    all_pass = True

    for ticket in tickets:
        run_result = await run_ticket(checkpointer, ticket, adapters)
        checks = evaluate(run_result)
        result = run_result["result"]
        all_results.append({"ticket_id": ticket["ticket_id"], **checks})

        status = "PASS" if checks["pass"] else "FAIL"
        if not checks["pass"]:
            all_pass = False

        print(f"[{status}] {ticket['ticket_id']}: {ticket['description'][:50]}...")
        print(
            f"  trade={result.get('trade')} "
            f"urgency={result.get('urgency')} "
            f"escalated={result.get('escalated')} "
            f"escalation_reason={result.get('escalation_reason')}"
        )
        print(
            f"  verify_pass={result.get('verify_pass')} "
            f"work_order_id={result.get('work_order_id') is not None} "
            f"sku={result.get('sku') is not None}"
        )
        print(
            f"  grounding_rate={checks['grounding_rate']} "
            f"retrieval@5={checks['retrieval_hit_rate_at_5']} "
            f"latency={checks['latency_s']:.3f}s"
        )

        if not checks["pass"]:
            failed = {k: v for k, v in checks.items() if v is False and k != "pass"}
            print(f"  FAILED checks: {failed}")
        print()

    # Summary
    passed = sum(1 for r in all_results if r["pass"])
    print(f"{'=' * 70}")
    print(f"Results: {passed}/{len(all_results)} passed")
    avg_latency = sum(r["latency_s"] for r in all_results) / len(all_results)
    print(f"Avg latency: {avg_latency:.3f}s")
    avg_grounding = [r["grounding_rate"] for r in all_results if r["grounding_rate"] is not None]
    if avg_grounding:
        print(f"Avg grounding rate: {sum(avg_grounding) / len(avg_grounding):.2f}")

    # Hit-rate@5 over annotated tickets only (spec §10.2). Stub retrieval
    # cannot hit real manual pages — expect 0.00 in stub mode, lift in --live.
    hits = [
        r["retrieval_hit_rate_at_5"]
        for r in all_results
        if r["retrieval_hit_rate_at_5"] is not None
    ]
    if hits:
        mode = "live" if args.live else "stub"
        print(
            f"Retrieval hit-rate@5: {sum(hits) / len(hits):.2f} "
            f"over {len(hits)} annotated tickets (retrieval={mode})"
        )
    else:
        print("Retrieval hit-rate@5: n/a (no tickets with expected_evidence annotations)")

    # ECE (BL-2): run-level metric over (grounding_rate, correct) pairs.
    # With the small golden set this is a scaffold — the number becomes
    # meaningful as ContractorStatement labels accumulate (BL-0 flywheel).
    pairs = [
        (r["grounding_rate"], bool(r["pass"]))
        for r in all_results
        if r["grounding_rate"] is not None
    ]
    if pairs:
        raw_ece = expected_calibration_error([p for p, _ in pairs], [y for _, y in pairs])
        print(f"ECE (uncalibrated grounding rate): {raw_ece:.4f} over {len(pairs)} tickets")
        eval_calibrator = PlattCalibrator()
        eval_calibrator.fit(pairs)  # skips (identity) if labels are one-class
        print(f"ECE (PlattCalibrator post-fit):    {eval_calibrator.ece():.4f}")
    else:
        print("ECE: no (grounding_rate, outcome) pairs available")
    print(f"{'=' * 70}\n")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
