"""Graph assembly — wires the pipeline nodes with PostgresSaver (spec §4).

Every node runs under the checkpointer (INV-6).
CLARIFY uses interrupt() — graph pauses, pending_question surfaced via API.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from hero.graph.nodes.clarify import clarify
from hero.graph.nodes.diagnose import make_diagnose
from hero.graph.nodes.intake import intake
from hero.graph.nodes.outcome import outcome
from hero.graph.nodes.procure import make_procure
from hero.graph.nodes.resolve import resolve
from hero.graph.nodes.retrieve import make_retrieve
from hero.graph.nodes.safety_gate import safety_gate
from hero.graph.nodes.triage import make_triage
from hero.graph.nodes.verify import make_verify
from hero.graph.state import GraphState
from hero.interfaces.calibrator import Calibrator
from hero.interfaces.catalog import CatalogResolver
from hero.interfaces.embedder import Embedder
from hero.interfaces.reranker import Reranker
from hero.interfaces.vlm import VLM
from hero.observability import traced_node


def _route_after_triage(state: dict[str, Any]) -> str:
    """Conditional edge: TRIAGE → retrieve_fast | retrieve on complexity (BL-4).

    Only an explicit "simple" takes the fast path — anything else
    (standard, complex, missing) gets full hybrid retrieval.
    """
    if state.get("complexity") == "simple":
        return "retrieve_fast"
    return "retrieve"


def _route_after_retrieve(state: dict[str, Any]) -> str:
    """Conditional edge: RETRIEVE → CLARIFY or DIAGNOSE.

    If pending_question is set and clarify_rounds < 3 → CLARIFY.
    Otherwise → DIAGNOSE.
    """
    if state.get("pending_question") and state.get("clarify_rounds", 0) < 3:
        return "clarify"
    return "diagnose"


def _route_after_clarify(state: dict[str, Any]) -> str:
    """After CLARIFY: always loop back to full RETRIEVE.

    A ticket that needed clarification is by definition not "simple" —
    the loop never re-enters the fast path (BL-4).
    """
    return "retrieve"


def _route_after_safety_gate(state: dict[str, Any]) -> str:
    """SAFETY_GATE → ESCALATE (end) or RESOLVE.

    Escalated tickets terminate; non-escalated proceed to RESOLVE.
    """
    if state.get("escalated"):
        return str(END)
    return "resolve"


def build_graph(
    *,
    embedder: Embedder,
    reranker: Reranker,
    calibrator: Calibrator,
    vlm: VLM,
    catalog: CatalogResolver,
    checkpointer: BaseCheckpointSaver[Any],
    grounding_threshold: float = 0.8,
    grounding_threshold_strict: float = 1.0,
    qdrant_client: Any | None = None,
) -> Any:
    """Assemble the full ticket pipeline graph.

    Returns a compiled LangGraph with PostgresSaver checkpointer (INV-6).
    If qdrant_client is provided, RETRIEVE uses real hybrid retrieval;
    otherwise, it produces stub evidence.
    """
    # Create node functions with injected adapters
    triage_fn = make_triage(vlm)
    # BOTH paths get the VLM for the P4-5 sufficiency check (INV-5 rider):
    # a triage "simple" verdict must never let an insufficient ticket reach
    # DIAGNOSE unasked. An insufficient fast-path ticket CLARIFYs and loops
    # back into the FULL path (CLARIFY always re-enters `retrieve`, BL-4).
    # The check runs at most once per ticket — never after a clarify round.
    retrieve_fn = make_retrieve(embedder, reranker, qdrant_client=qdrant_client, vlm=vlm)
    retrieve_fast_fn = make_retrieve(
        embedder, reranker, qdrant_client=qdrant_client, fast_path=True, vlm=vlm
    )
    diagnose_fn = make_diagnose(vlm)
    verify_fn = make_verify(vlm, calibrator, grounding_threshold, grounding_threshold_strict)
    procure_fn = make_procure(catalog)

    # Build the state graph
    graph = StateGraph(GraphState)

    # Add all nodes — each wrapped in a Langfuse span (spec §11; no-op
    # passthrough when Langfuse is not configured).
    graph.add_node("intake", traced_node("intake", intake))
    graph.add_node("triage", traced_node("triage", triage_fn))
    graph.add_node("retrieve", traced_node("retrieve", retrieve_fn))
    graph.add_node("retrieve_fast", traced_node("retrieve_fast", retrieve_fast_fn))  # BL-4
    graph.add_node("clarify", traced_node("clarify", clarify))
    graph.add_node("diagnose", traced_node("diagnose", diagnose_fn))
    graph.add_node("verify", traced_node("verify", verify_fn))
    graph.add_node("safety_gate", traced_node("safety_gate", safety_gate))
    graph.add_node("resolve", traced_node("resolve", resolve))
    graph.add_node("procure", traced_node("procure", procure_fn))
    graph.add_node("outcome", traced_node("outcome", outcome))

    # Wire edges
    # START → INTAKE → TRIAGE
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "triage")

    # TRIAGE → retrieve_fast (complexity=="simple") | retrieve (BL-4)
    graph.add_conditional_edges("triage", _route_after_triage, ["retrieve", "retrieve_fast"])

    # RETRIEVE (either path) → CLARIFY or DIAGNOSE
    graph.add_conditional_edges("retrieve", _route_after_retrieve, ["clarify", "diagnose"])
    graph.add_conditional_edges("retrieve_fast", _route_after_retrieve, ["clarify", "diagnose"])

    # CLARIFY → RETRIEVE (loop back)
    graph.add_conditional_edges("clarify", _route_after_clarify, ["retrieve"])

    # DIAGNOSE → VERIFY (unconditional — never skippable, INV-1/INV-8)
    graph.add_edge("diagnose", "verify")

    # VERIFY → SAFETY_GATE (unconditional — INV-1)
    graph.add_edge("verify", "safety_gate")

    # SAFETY_GATE → END (escalated) or RESOLVE
    graph.add_conditional_edges("safety_gate", _route_after_safety_gate, ["resolve", END])

    # RESOLVE → PROCURE → OUTCOME → END
    graph.add_edge("resolve", "procure")
    graph.add_edge("procure", "outcome")
    graph.add_edge("outcome", END)

    return graph.compile(checkpointer=checkpointer)
