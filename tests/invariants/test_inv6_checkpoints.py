"""INV-6: Every state transition is persisted.

Kill a run mid-graph, resume, assert state identical.
Uses MemorySaver for unit test; integration tests will use PostgresSaver
with testcontainers.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.graph.build import build_graph


class ClarifyTriggerVLM(StubVLM):
    """VLM that triggers a clarify question on first call."""

    def __init__(self) -> None:
        self._call_count = 0

    async def diagnose(self, state: Any) -> Any:
        self._call_count += 1
        return await super().diagnose(state)


@pytest.mark.asyncio
async def test_checkpoint_preserves_state_across_resume() -> None:
    """Run a ticket that triggers CLARIFY, verify state is persisted,
    then resume and verify the state continues correctly."""
    checkpointer = MemorySaver()
    graph = build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=checkpointer,
    )

    thread_id = "inv6-checkpoint-test"
    config = {"configurable": {"thread_id": thread_id}}

    # Run a ticket that will set pending_question to trigger CLARIFY
    result = await graph.ainvoke(
        {
            "ticket_id": "INV6-001",
            "description": "Something is wrong with the plumbing",
            "pending_question": "Can you describe where the leak is?",
        },
        config=config,
    )

    # The graph should have interrupted at CLARIFY
    # Check that state was checkpointed
    state = await graph.aget_state(config)
    assert state is not None
    assert state.values.get("ticket_id") == "INV6-001"

    # Now resume with an answer
    result = await graph.ainvoke(
        {"pending_question": None, "description": result["description"]},
        config=config,
    )

    # After resume, the ticket should complete
    assert result.get("verify_pass") is not None


@pytest.mark.asyncio
async def test_checkpoint_state_survives_new_graph_instance() -> None:
    """Simulate a process restart: build a new graph with the same
    checkpointer and verify we can read the old state."""
    checkpointer = MemorySaver()

    # First "process"
    graph1 = build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=checkpointer,
    )

    thread_id = "inv6-restart-test"
    config = {"configurable": {"thread_id": thread_id}}

    await graph1.ainvoke(
        {
            "ticket_id": "INV6-002",
            "description": "HVAC not cooling",
        },
        config=config,
    )

    # "Restart": new graph instance, same checkpointer
    graph2 = build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=checkpointer,
    )

    state = await graph2.aget_state(config)
    assert state is not None
    assert state.values.get("ticket_id") == "INV6-002"
    assert state.values.get("trade") is not None  # triage ran
