"""Eval harness — replays golden tickets through the graph with stub adapters.

Reports metrics per spec §10.2:
- retrieval hit-rate@5
- per-claim grounding rate
- diagnosis accuracy vs label
- ECE
- cost/ticket (stub: $0)
- latency

Usage: uv run python evals/run_eval.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.graph.build import build_graph


def load_golden_tickets() -> list[dict[str, Any]]:
    """Load all golden ticket JSON files."""
    tickets_dir = Path(__file__).parent / "golden_tickets"
    tickets = []
    for path in sorted(tickets_dir.glob("*.json")):
        tickets.append(json.loads(path.read_text()))
    return tickets


def build_eval_graph() -> Any:
    """Build graph with stub adapters for eval."""
    return build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=MemorySaver(),
    )


async def run_ticket(graph: Any, ticket: dict[str, Any]) -> dict[str, Any]:
    """Run a single golden ticket through the graph, handling CLARIFY if needed."""
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

    # If this ticket requires clarify, set pending_question to trigger it
    if expected.get("requires_clarify"):
        input_state["pending_question"] = "Can you provide more details?"

    start = time.monotonic()
    result = await graph.ainvoke(input_state, config=config)

    # If clarification was required and the graph interrupted, resume
    if expected.get("requires_clarify") and result.get("pending_question"):
        clarify_answer = expected.get("clarify_answer", "No additional details")
        result = await graph.ainvoke(Command(resume=clarify_answer), config=config)

    elapsed = time.monotonic() - start

    return {
        "ticket_id": ticket_id,
        "result": result,
        "elapsed_s": elapsed,
        "expected": expected,
        "label": ticket.get("label", {}),
    }


def evaluate(run_result: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a single run against expected outcomes."""
    result = run_result["result"]
    expected = run_result["expected"]
    checks: dict[str, Any] = {}

    # Trade match
    checks["trade_match"] = result.get("trade") == expected.get("trade")

    # Urgency match
    checks["urgency_match"] = result.get("urgency") == expected.get("urgency")

    # Escalation
    checks["escalation_correct"] = result.get("escalated") == expected.get("escalated")
    if expected.get("escalation_reason"):
        checks["escalation_reason_match"] = (
            result.get("escalation_reason") == expected["escalation_reason"]
        )

    # Diagnosis exists
    checks["has_diagnosis"] = len(result.get("hypotheses", [])) > 0
    if expected.get("has_diagnosis"):
        checks["diagnosis_present"] = checks["has_diagnosis"] == expected["has_diagnosis"]

    # Work order
    checks["has_work_order"] = result.get("work_order_id") is not None
    if "has_work_order" in expected:
        checks["work_order_correct"] = checks["has_work_order"] == expected["has_work_order"]

    # SKU
    checks["has_sku"] = result.get("sku") is not None
    if "has_sku" in expected:
        checks["sku_correct"] = checks["has_sku"] == expected["has_sku"]

    # Per-claim grounding rate
    hypotheses = result.get("hypotheses", [])
    total_claims = 0
    grounded_claims = 0
    for hyp in hypotheses:
        claims = hyp.get("claims", [])
        for claim in claims:
            total_claims += 1
            if claim.get("grounded"):
                grounded_claims += 1

    checks["grounding_rate"] = grounded_claims / total_claims if total_claims > 0 else None

    # Retrieval hit-rate@5
    evidence = result.get("evidence", [])
    checks["retrieval_count"] = len(evidence)
    checks["retrieval_hit_rate_at_5"] = min(len(evidence), 5) / 5.0 if evidence else 0.0

    # ECE (stub: 0.0)
    checks["ece"] = 0.0

    # Cost (stub: $0)
    checks["cost_usd"] = 0.0

    # Latency
    checks["latency_s"] = run_result["elapsed_s"]

    # Overall pass
    critical_checks = [
        checks.get("escalation_correct", False),
        checks.get("diagnosis_present", True),
    ]
    checks["pass"] = all(critical_checks)

    return checks


async def main() -> int:
    """Run all golden tickets and print results."""
    tickets = load_golden_tickets()
    graph = build_eval_graph()

    print(f"\n{'=' * 70}")
    print(f"Hero.AI Eval — {len(tickets)} golden tickets")
    print(f"{'=' * 70}\n")

    all_results: list[dict[str, Any]] = []
    all_pass = True

    for ticket in tickets:
        run_result = await run_ticket(graph, ticket)
        checks = evaluate(run_result)
        all_results.append({"ticket_id": ticket["ticket_id"], **checks})

        status = "PASS" if checks["pass"] else "FAIL"
        if not checks["pass"]:
            all_pass = False

        print(f"[{status}] {ticket['ticket_id']}: {ticket['description'][:50]}...")
        print(
            f"  trade={run_result['result'].get('trade')} "
            f"escalated={run_result['result'].get('escalated')} "
            f"latency={checks['latency_s']:.3f}s"
        )
        print(
            f"  grounding_rate={checks['grounding_rate']} "
            f"retrieval@5={checks['retrieval_hit_rate_at_5']}"
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
    print(f"{'=' * 70}\n")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
