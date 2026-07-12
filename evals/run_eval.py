"""Eval harness — replays golden tickets through the graph.

Reports metrics per spec §10.2:
- retrieval hit-rate@5 (against expected_evidence annotations)
- per-claim grounding rate
- diagnosis accuracy vs label
- ECE
- cost/ticket, split by model tier — measured from the VLM adapter's
  accumulated LiteLLM usage (drain_usage), never hard-coded. Stub: $0.
- latency: per ticket AND per node (time between graph stream updates —
  includes checkpointer overhead per node)

Repeatability: --runs N replays every ticket N times and reports
mean/min/max on grounding rate and cost. Primary-tier model outputs are
non-deterministic (DEC-20: newer Anthropic models reject the temperature
param, so outputs cannot be pinned) — single-run numbers are samples,
not point estimates.

Sufficiency tax (P4-5d): cost FLAGs on any run (> ~$0.01/ticket).
Latency is a TREND gate — it FLAGs only when the --runs N (N>1)
across-runs average exceeds 2.5s/ticket; a single run over 2.5s prints
a non-gating note (single-sample provider variance, per DEC-20 above).

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


# (doc_id, pdf_path, manufacturer, model_codes) — one fixture manual per trade
# in the golden set, so grounding is a metric that can actually move (P3-1.5).
_FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
FIXTURE_MANUALS = [
    ("test-manual", _FIXTURES_DIR / "test_plumbing_manual.pdf", "ACME", ["PL-2000"]),
    ("test-hvac-manual", _FIXTURES_DIR / "test_hvac_manual.pdf", "ACME", ["AC-3000"]),
    ("test-gas-manual", _FIXTURES_DIR / "test_gas_manual.pdf", "ACME", ["GF-8000"]),
]


def _ensure_fixtures_ingested(client: Any, embedder: Any) -> None:
    """Ingest any fixture manual missing from the Qdrant collection (--live)."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from hero.ingestion.ingest import COLLECTION_NAME, ingest_pdf

    collection_exists = COLLECTION_NAME in [c.name for c in client.get_collections().collections]
    for doc_id, pdf_path, manufacturer, model_codes in FIXTURE_MANUALS:
        if collection_exists:
            existing = client.count(
                COLLECTION_NAME,
                count_filter=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
                exact=True,
            ).count
            if existing > 0:
                continue
        print(f"[QDRANT] ingesting fixture {doc_id!r} from {pdf_path.name}...")
        ingest_pdf(
            pdf_path=str(pdf_path),
            doc_id=doc_id,
            manufacturer=manufacturer,
            model_codes=model_codes,
            embedder=embedder,
            client=client,
        )
        collection_exists = True


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

    client = QdrantClient(url=settings.qdrant_url, timeout=30)
    client.get_collections()  # fail loudly if Qdrant unreachable

    embedder = ColModernVBertEmbedder()
    _ensure_fixtures_ingested(client, embedder)

    # Index-integrity canary (P3-4): version-stamp sweep + live BM25 probe.
    # A stale fixture index is re-ingested once (idempotent point IDs
    # overwrite in place); anything still wrong after that fails the run.
    from hero.ingestion.ingest import ingest_pdf
    from hero.retrieval.integrity import IndexIntegrityError, bm25_canary, check_index_integrity

    try:
        check_index_integrity(client)
    except IndexIntegrityError as exc:
        print(f"[QDRANT] integrity check failed ({exc}) — re-ingesting fixtures...")
        for doc_id, pdf_path, manufacturer, model_codes in FIXTURE_MANUALS:
            ingest_pdf(
                pdf_path=str(pdf_path),
                doc_id=doc_id,
                manufacturer=manufacturer,
                model_codes=model_codes,
                embedder=embedder,
                client=client,
            )
        check_index_integrity(client)  # still stale → raise, don't mask
    bm25_canary(client, "manual")  # every fixture contains the token "manual"
    print("[QDRANT] index integrity OK (version stamp + BM25 canary)")

    # Empty override = verify tier (DEC-18 as amended)
    triage_tier = settings.vlm_model_triage or f"{settings.vlm_model_verify} (verify)"
    print(
        f"[ADAPTERS] live (VLM=LiteLLMVLM primary={settings.vlm_model_primary} "
        f"verify={settings.vlm_model_verify} fallback={settings.vlm_model_fallback} "
        f"triage={triage_tier}, "
        f"embedder=ColModernVBERT, reranker=BGE, qdrant={settings.qdrant_url})"
    )
    return {
        "embedder": embedder,
        "reranker": BGEReranker(),
        "vlm": LiteLLMVLM(
            primary_model=settings.vlm_model_primary,
            verify_model=settings.vlm_model_verify,
            fallback_model=settings.vlm_model_fallback,
            triage_model=settings.vlm_model_triage,
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


async def _stream_collect(
    graph: Any,
    payload: Any,
    config: dict[str, Any],
    node_latency: dict[str, float],
) -> dict[str, Any]:
    """Drive the graph via astream(updates) recording per-node wall time.

    Per-node latency = time between successive update events; it includes
    per-node checkpointer overhead. Final state read back via aget_state.
    """
    t_prev = time.monotonic()
    async for chunk in graph.astream(payload, config=config, stream_mode="updates"):
        now = time.monotonic()
        for node in chunk:
            if not node.startswith("__"):  # skip __interrupt__ marker
                node_latency[node] = node_latency.get(node, 0.0) + (now - t_prev)
        t_prev = now
    state = await graph.aget_state(config)
    return dict(state.values)


async def run_ticket(
    checkpointer: Any,
    ticket: dict[str, Any],
    adapters: dict[str, Any],
    run_idx: int = 0,
) -> dict[str, Any]:
    """Run a single golden ticket through the graph, handling CLARIFY if needed.

    For CLARIFY tickets: simulates a process restart by destroying the graph
    instance after interrupt and creating a new one with the same checkpointer.
    With AsyncPostgresSaver, this proves real DB round-trip resumability (INV-6).
    """
    ticket_id = ticket["ticket_id"]
    expected = ticket["expected"]
    thread_id = f"eval-{ticket_id}-r{run_idx}"
    config = {"configurable": {"thread_id": thread_id}}

    input_state: dict[str, Any] = {
        "ticket_id": ticket_id,
        "description": ticket["description"],
        "media": ticket.get("media", []),
        "sensor_readings": ticket.get("sensor_readings", []),
    }

    # Legacy injected-CLARIFY path (EVAL-002/005): exercises checkpoint resume
    # across a simulated restart. Organic CLARIFY (P4-5, expected_clarify) is
    # NOT injected — the sufficiency check must raise the question itself.
    injected = bool(expected.get("requires_clarify"))
    if injected:
        input_state["pending_question"] = "Can you provide more details?"

    # Reset the adapter's usage counters so cost is attributed per ticket.
    drain = getattr(adapters["vlm"], "drain_usage", None)
    if callable(drain):
        drain()

    node_latency: dict[str, float] = {}
    start = time.monotonic()

    # --- First graph instance ---
    graph1 = _build_graph(checkpointer, adapters)
    result = await _stream_collect(graph1, input_state, config, node_latency)

    # If CLARIFY interrupted (injected OR organic via P4-5 sufficiency),
    # simulate a process restart and resume with the annotated answer.
    clarify_question: str | None = None
    organic_clarify = False
    if result.get("pending_question"):
        clarify_question = result["pending_question"]
        organic_clarify = not injected
        origin = "organic (P4-5 sufficiency)" if organic_clarify else "injected"
        print(f"  [CLARIFY] Graph interrupted ({origin}). pending_question={clarify_question!r}")
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
        result = await _stream_collect(graph2, Command(resume=clarify_answer), config, node_latency)
        print(f"  [CLARIFY] Resumed successfully. clarify_rounds={result.get('clarify_rounds')}")

    elapsed = time.monotonic() - start

    # Real per-tier usage accumulated by the adapter during this ticket.
    cost_by_tier: dict[str, dict[str, float]] = drain() if callable(drain) else {}

    return {
        "ticket_id": ticket_id,
        "result": result,
        "elapsed_s": elapsed,
        "node_latency": node_latency,
        "cost_by_tier": cost_by_tier,
        "clarify_question": clarify_question,
        "organic_clarify": organic_clarify,
        "expected": expected,
        "expected_complexity": ticket.get("expected_complexity"),
        "expected_evidence": ticket.get("expected_evidence"),
        "expected_claims": ticket.get("expected_claims"),
        "label": ticket.get("label", {}),
    }


def evaluate(run_result: dict[str, Any], *, live: bool = False) -> dict[str, Any]:
    """Evaluate a single run against expected outcomes."""
    result = run_result["result"]
    expected = run_result["expected"]
    checks: dict[str, Any] = {}

    checks["trade_match"] = result.get("trade") == expected.get("trade")
    checks["urgency_match"] = result.get("urgency") == expected.get("urgency")
    checks["escalation_correct"] = result.get("escalated") == expected.get("escalated")

    # BL-4 complexity routing: which retrieval path actually ran (from the
    # node-latency trace — retrieve_fast only exists on the fast path).
    checks["complexity"] = result.get("complexity")
    checks["path"] = "fast" if "retrieve_fast" in run_result.get("node_latency", {}) else "full"
    # P4-0: a "complex" pin only gates in --live — StubVLM triage IS the DEC-21
    # keyword fallback, which never returns "complex" by design. Tracked
    # (non-gating) via expected_complexity in stub mode regardless.
    if "complexity" in expected and (live or expected["complexity"] != "complex"):
        checks["complexity_match"] = result.get("complexity") == expected["complexity"]

    # P3-4 rider: every golden ticket carries a non-gating expected_complexity
    # annotation so routing stability is a tracked metric, not an anecdote.
    checks["expected_complexity"] = run_result.get("expected_complexity")
    checks["routing_mismatch"] = (
        checks["expected_complexity"] is not None
        and result.get("complexity") != checks["expected_complexity"]
    )

    # P4-5 eval gate: organic CLARIFY must fire exactly when annotated —
    # a golden ticket that passes without questions must never regress into
    # question-asking, and EVAL-006 must organically ask.
    checks["organic_clarify"] = run_result.get("organic_clarify", False)
    checks["clarify_question"] = run_result.get("clarify_question")
    checks["clarify_behavior_correct"] = checks["organic_clarify"] == bool(
        expected.get("expected_clarify")
    )

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

    # Per-claim grounding (BL-6/DEC-6): overall and split by claim type,
    # since part_number and descriptive claims carry different thresholds.
    hypotheses = result.get("hypotheses", [])
    total_claims = 0
    grounded_claims = 0
    by_type: dict[str, list[int]] = {}  # type -> [grounded, total]
    for hyp in hypotheses:
        for claim in hyp.get("claims", []):
            total_claims += 1
            ctype = claim.get("claim_type") or "descriptive"
            grounded_n, total_n = by_type.get(ctype, [0, 0])
            is_grounded = bool(claim.get("grounded"))
            by_type[ctype] = [grounded_n + int(is_grounded), total_n + 1]
            if is_grounded:
                grounded_claims += 1
    checks["grounding_rate"] = grounded_claims / total_claims if total_claims > 0 else None
    checks["claim_counts_by_type"] = {t: n for t, (_, n) in by_type.items()}
    checks["grounding_rate_by_type"] = {t: g / n for t, (g, n) in by_type.items() if n > 0}

    # Claim-level annotation check (BL-6). Reported, not run-blocking.
    expected_claims = run_result.get("expected_claims")
    if expected_claims and checks["grounding_rate"] is not None:
        checks["claim_grounding_meets_min"] = (
            checks["grounding_rate"] >= expected_claims["min_grounding_rate"]
        )
    else:
        checks["claim_grounding_meets_min"] = None

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
    # Measured cost from the adapter's LiteLLM usage (P3-1.5) — $0 for stubs.
    cost_by_tier = run_result.get("cost_by_tier", {})
    checks["cost_by_tier"] = cost_by_tier
    checks["cost_usd"] = sum(t["cost_usd"] for t in cost_by_tier.values())
    checks["latency_s"] = run_result["elapsed_s"]
    checks["node_latency_s"] = run_result.get("node_latency", {})

    critical_checks = [
        checks.get("escalation_correct", False),
        checks.get("diagnosis_present", True),
        # BL-4: gated only when the golden ticket pins an expected complexity.
        checks.get("complexity_match", True),
        # P4-5: organic CLARIFY regression gate.
        checks.get("clarify_behavior_correct", True),
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
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Replay every ticket N times and report mean/min/max on grounding "
        "and cost. Primary-tier outputs are non-deterministic (DEC-20).",
    )
    args = parser.parse_args()

    tickets = load_golden_tickets()
    checkpointer = await _make_checkpointer()
    adapters = _make_adapters(live=args.live)

    print(f"\n{'=' * 70}")
    print(
        f"Hero.AI Eval — {len(tickets)} golden tickets "
        f"(mode={'LIVE' if args.live else 'stub'}, runs={args.runs})"
    )
    print(f"{'=' * 70}\n")

    all_results: list[dict[str, Any]] = []
    all_pass = True

    for run_idx in range(args.runs):
        if args.runs > 1:
            print(f"----- run {run_idx + 1}/{args.runs} -----")
        for ticket in tickets:
            run_result = await run_ticket(checkpointer, ticket, adapters, run_idx=run_idx)
            checks = evaluate(run_result, live=args.live)
            result = run_result["result"]
            all_results.append({"ticket_id": ticket["ticket_id"], "run": run_idx, **checks})

            status = "PASS" if checks["pass"] else "FAIL"
            if not checks["pass"]:
                all_pass = False

            print(f"[{status}] {ticket['ticket_id']}: {ticket['description'][:50]}...")
            print(
                f"  trade={result.get('trade')} "
                f"urgency={result.get('urgency')} "
                f"complexity={result.get('complexity')} "
                f"path={checks['path']} "
                f"escalated={result.get('escalated')} "
                f"escalation_reason={result.get('escalation_reason')}"
            )
            print(
                f"  verify_pass={result.get('verify_pass')} "
                f"work_order_id={result.get('work_order_id') is not None} "
                f"sku={result.get('sku') is not None}"
            )
            if checks["clarify_question"]:
                origin = "organic" if checks["organic_clarify"] else "injected"
                print(f"  clarify[{origin}]: {checks['clarify_question']!r}")
            print(
                f"  grounding_rate={checks['grounding_rate']} "
                f"by_type={checks['grounding_rate_by_type']} "
                f"claims={checks['claim_counts_by_type']} "
                f"meets_min={checks['claim_grounding_meets_min']}"
            )
            print(
                f"  retrieval@5={checks['retrieval_hit_rate_at_5']} "
                f"latency={checks['latency_s']:.3f}s "
                f"cost=${checks['cost_usd']:.4f}"
            )
            if checks["cost_by_tier"]:
                for tier, usage in sorted(checks["cost_by_tier"].items()):
                    print(
                        f"    cost[{tier}]: ${usage['cost_usd']:.4f} "
                        f"({usage['calls']:.0f} calls, "
                        f"{usage['prompt_tokens']:.0f}/{usage['completion_tokens']:.0f} tok, "
                        f"{usage.get('latency_s', 0.0):.2f}s)"
                    )
            if checks["node_latency_s"]:
                node_parts = " ".join(
                    f"{node}={t:.2f}s" for node, t in checks["node_latency_s"].items()
                )
                print(f"    nodes: {node_parts}")

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

    # Per-node latency averaged across all ticket runs (P3-1.5).
    node_totals: dict[str, list[float]] = {}
    for r in all_results:
        for node, t in r.get("node_latency_s", {}).items():
            node_totals.setdefault(node, []).append(t)
    if node_totals:
        parts = " ".join(f"{n}={sum(ts) / len(ts):.2f}s" for n, ts in node_totals.items())
        print(f"Avg latency per node: {parts}")

    # Cost: total for the whole eval run, split by tier (P3-1.5).
    total_cost = sum(r["cost_usd"] for r in all_results)
    tier_costs: dict[str, float] = {}
    for r in all_results:
        for tier, usage in r.get("cost_by_tier", {}).items():
            tier_costs[tier] = tier_costs.get(tier, 0.0) + usage["cost_usd"]
    print(f"Total run cost: ${total_cost:.4f}", end="")
    if tier_costs:
        split = " ".join(f"{t}=${c:.4f}" for t, c in sorted(tier_costs.items()))
        print(f" ({split})")
    else:
        print()
    if len(all_results) > 0:
        print(f"Avg cost/ticket: ${total_cost / len(all_results):.4f}")

    # BL-4 DoD: cost/latency split by routing path (fast vs full).
    print("\nPath split (BL-4 — fast vs full):")
    for path in ("fast", "full"):
        rs = [r for r in all_results if r.get("path") == path]
        if not rs:
            print(f"  {path}: n=0")
            continue
        avg_lat = sum(r["latency_s"] for r in rs) / len(rs)
        avg_cost = sum(r["cost_usd"] for r in rs) / len(rs)
        retrieve_node = "retrieve_fast" if path == "fast" else "retrieve"
        r_lats = [
            r["node_latency_s"][retrieve_node]
            for r in rs
            if retrieve_node in r.get("node_latency_s", {})
        ]
        r_lat = f"{sum(r_lats) / len(r_lats):.2f}s" if r_lats else "n/a"
        print(
            f"  {path}: n={len(rs)} avg_latency={avg_lat:.3f}s "
            f"avg_cost=${avg_cost:.4f} avg_{retrieve_node}={r_lat}"
        )

    # P4-5d: the sufficiency check is a per-ticket tax on the full path —
    # report its cost/latency and flag if it exceeds ~$0.01 or ~2s/ticket.
    print("\nSufficiency check (P4-5d — per-ticket tax on the full path):")
    suff = [r for r in all_results if "verify/sufficiency" in r.get("cost_by_tier", {})]
    if suff:
        n = len(suff)
        avg_calls = sum(r["cost_by_tier"]["verify/sufficiency"]["calls"] for r in suff) / n
        avg_cost = sum(r["cost_by_tier"]["verify/sufficiency"]["cost_usd"] for r in suff) / n
        avg_lat = (
            sum(r["cost_by_tier"]["verify/sufficiency"].get("latency_s", 0.0) for r in suff) / n
        )
        print(
            f"  n={n} tickets paid the check: avg calls={avg_calls:.1f} "
            f"avg cost=${avg_cost:.4f} avg latency={avg_lat:.2f}s"
        )
        # Cost flags on any run. Latency is a TREND gate: single-run numbers
        # are samples, not point estimates (DEC-20 — provider-side variance on
        # one ~1.5K-token call), so it flags only when the --runs N (N>1)
        # across-runs average exceeds 2.5s.
        if avg_cost > 0.01:
            print("  FLAG: sufficiency cost exceeds ~$0.01 per ticket — review before shipping")
        if args.runs > 1 and avg_lat > 2.5:
            print(
                f"  FLAG: sufficiency latency trend over {args.runs} runs exceeds "
                "2.5s per ticket — review before shipping"
            )
        elif args.runs == 1 and avg_lat > 2.5:
            print(
                "  note: single-run latency above 2.5s — not gating; "
                "confirm the trend with --runs N"
            )
    else:
        reason = (
            "no full-path ticket paid the check" if args.live else "stub adapters accrue no usage"
        )
        print(f"  n/a ({reason})")

    # P3-4 rider: routing stability vs expected_complexity annotations.
    # NON-GATING — tracked so triage drift is a metric, not an anecdote.
    annotated = [r for r in all_results if r.get("expected_complexity") is not None]
    if annotated:
        mismatches = [r for r in annotated if r.get("routing_mismatch")]
        print(
            f"\nRouting stability (non-gating): {len(mismatches)}/{len(annotated)} "
            f"runs deviated from expected_complexity"
        )
        by_tid: dict[str, list[dict[str, Any]]] = {}
        for r in annotated:
            by_tid.setdefault(r["ticket_id"], []).append(r)
        for tid, rs in sorted(by_tid.items()):
            got = [str(r.get("complexity")) for r in rs]
            expected_c = rs[0]["expected_complexity"]
            n_bad = sum(1 for r in rs if r.get("routing_mismatch"))
            marker = " <-- MISMATCH" if n_bad else ""
            print(f"  {tid}: expected={expected_c} got={'/'.join(got)}{marker}")

    # Spread across repeated runs (DEC-20: primary tier is non-deterministic).
    if args.runs > 1:
        print(f"\nSpread over {args.runs} runs (DEC-20 — mean/min/max):")
        by_ticket: dict[str, list[dict[str, Any]]] = {}
        for r in all_results:
            by_ticket.setdefault(r["ticket_id"], []).append(r)
        for ticket_id, rs in sorted(by_ticket.items()):
            g = [r["grounding_rate"] for r in rs if r["grounding_rate"] is not None]
            c = [r["cost_usd"] for r in rs]
            if g:
                g_str = f"grounding {sum(g) / len(g):.2f}/{min(g):.2f}/{max(g):.2f}"
            else:
                g_str = "grounding n/a"
            print(
                f"  {ticket_id}: {g_str}  cost ${sum(c) / len(c):.4f}/${min(c):.4f}/${max(c):.4f}"
            )
    avg_grounding = [r["grounding_rate"] for r in all_results if r["grounding_rate"] is not None]
    if avg_grounding:
        print(f"Avg grounding rate: {sum(avg_grounding) / len(avg_grounding):.2f}")

    # Per-claim-type grounding across the run (BL-6/DEC-6)
    agg_by_type: dict[str, list[float]] = {}
    for r in all_results:
        for ctype, rate in r.get("grounding_rate_by_type", {}).items():
            agg_by_type.setdefault(ctype, []).append(rate)
    for ctype, rates in sorted(agg_by_type.items()):
        print(f"Grounding rate [{ctype}]: {sum(rates) / len(rates):.2f} over {len(rates)} tickets")

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

    from hero.observability import flush

    flush()  # drain buffered Langfuse spans (no-op when unconfigured)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
