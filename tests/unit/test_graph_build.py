"""Test that the graph compiles and runs a simple ticket end-to-end with stubs."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.graph.build import build_graph


def _build_stub_graph() -> object:
    return build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=MemorySaver(),
    )


@pytest.mark.asyncio
async def test_simple_plumbing_ticket_completes() -> None:
    """A simple plumbing ticket should flow end-to-end without escalation."""
    graph = _build_stub_graph()
    config = {"configurable": {"thread_id": "test-plumbing-001"}}

    result = await graph.ainvoke(
        {
            "ticket_id": "T-001",
            "description": "Leaking pipe under kitchen sink",
        },
        config=config,
    )

    assert result["trade"] == "plumbing"
    assert result["urgency"] == "urgent"
    assert result["verify_pass"] is True
    assert result["escalated"] is False
    assert result["work_order_id"] is not None
    assert result["sku"] is not None


@pytest.mark.asyncio
async def test_photo_carrying_ticket_completes() -> None:
    """Regression: media in the exact shape the public intake route produces
    must survive TicketState validation in DIAGNOSE (it once 500'd on the
    first photo ticket — MIME type instead of "image", sha256 missing)."""
    graph = _build_stub_graph()
    config = {"configurable": {"thread_id": "test-photo-001"}}

    result = await graph.ainvoke(
        {
            "ticket_id": "T-PHOTO",
            "description": "Leaking pipe under kitchen sink",
            "media": [
                {
                    "object_key": "public-intake/b/u/photo.jpg",
                    "media_type": "image",
                    "sha256": None,  # best-effort — HTTP-LAN phones can't hash
                }
            ],
        },
        config=config,
    )

    assert result["verify_pass"] is True
    assert result["escalated"] is False
    assert result["work_order_id"] is not None


@pytest.mark.asyncio
async def test_gas_ticket_escalates() -> None:
    """A gas ticket must escalate regardless of everything else (INV-1)."""
    graph = _build_stub_graph()
    config = {"configurable": {"thread_id": "test-gas-001"}}

    result = await graph.ainvoke(
        {
            "ticket_id": "T-002",
            "description": "Strong gas smell near furnace",
        },
        config=config,
    )

    assert result["trade"] == "gas"
    assert result["escalated"] is True
    assert result["escalation_reason"] == "hard_category"
    # Escalated tickets should NOT have work_order_id or sku
    assert result.get("work_order_id") is None
    assert result.get("sku") is None


@pytest.mark.asyncio
async def test_graph_has_all_ten_nodes() -> None:
    """Verify all 10 nodes are present in the compiled graph."""
    graph = _build_stub_graph()
    node_names = set(graph.get_graph().nodes.keys())
    expected = {
        "__start__",
        "__end__",
        "intake",
        "triage",
        "retrieve",
        "clarify",
        "diagnose",
        "verify",
        "safety_gate",
        "resolve",
        "procure",
        "outcome",
    }
    assert expected.issubset(node_names), f"Missing nodes: {expected - node_names}"
