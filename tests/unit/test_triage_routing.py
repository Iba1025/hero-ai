"""P3-3 (BL-4): VLM triage parsing, INV-1 fail-safes, and complexity routing.

Covers:
- parse_triage strict shapes (bad JSON / non-object / out-of-vocabulary).
- TRIAGE node: VLM result used; VLM failure → keyword fallback with
  complexity="standard" (never fast path); hazard-trade override and
  urgency floor (INV-1 — the VLM cannot classify away a keyword hazard).
- _route_after_triage: only explicit "simple" takes retrieve_fast.
- keyword_triage fallback heuristics (EVAL-004 description → simple).
- Stub fast-path retrieval: BM25-only, no rerank.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from hero.adapters.litellm_vlm import parse_triage
from hero.graph.build import _route_after_triage
from hero.graph.nodes.retrieve import make_retrieve
from hero.graph.nodes.triage import keyword_triage, make_triage
from hero.graph.state import TriageResult
from hero.interfaces.vlm import TriageParseError

# ---------------------------------------------------------------------------
# parse_triage
# ---------------------------------------------------------------------------


def test_parse_triage_valid() -> None:
    raw = json.dumps({"trade": "plumbing", "urgency": "routine", "complexity": "simple"})
    result = parse_triage(raw)
    assert result == TriageResult(trade="plumbing", urgency="routine", complexity="simple")


def test_parse_triage_bad_json() -> None:
    with pytest.raises(TriageParseError):
        parse_triage("not json {")


def test_parse_triage_non_object() -> None:
    with pytest.raises(TriageParseError):
        parse_triage(json.dumps(["plumbing", "routine", "simple"]))


@pytest.mark.parametrize(
    "payload",
    [
        {"trade": "carpentry", "urgency": "routine", "complexity": "simple"},
        {"trade": "plumbing", "urgency": "asap", "complexity": "simple"},
        {"trade": "plumbing", "urgency": "routine", "complexity": "trivial"},
        {"trade": "plumbing", "urgency": "routine"},  # missing field
    ],
)
def test_parse_triage_out_of_vocabulary(payload: dict[str, Any]) -> None:
    """TriageResult's Literal fields are the vocabulary gate."""
    with pytest.raises(TriageParseError):
        parse_triage(json.dumps(payload))


# ---------------------------------------------------------------------------
# TRIAGE node — VLM path, fallback, INV-1 fail-safes
# ---------------------------------------------------------------------------


class _FixedTriageVLM:
    """VLM stub whose triage() returns a fixed result or raises."""

    def __init__(self, result: TriageResult | None = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    async def triage(self, description: str) -> TriageResult:
        if self._exc is not None:
            raise self._exc
        assert self._result is not None
        return self._result


def test_node_uses_vlm_result() -> None:
    vlm = _FixedTriageVLM(TriageResult(trade="hvac", urgency="urgent", complexity="complex"))
    node = make_triage(vlm)
    out = asyncio.run(node({"description": "Rooftop unit intermittently short-cycling"}))
    assert out == {"trade": "hvac", "urgency": "urgent", "complexity": "complex"}


@pytest.mark.parametrize(
    "exc",
    [TriageParseError("bad shape"), RuntimeError("provider down")],
)
def test_node_vlm_failure_falls_back_to_keywords_full_path(exc: Exception) -> None:
    """Any VLM failure → keyword classifier with complexity="standard".

    A triage failure must never route a ticket to the reduced fast path,
    even when the keyword heuristic itself would say "simple".
    """
    node = make_triage(_FixedTriageVLM(exc=exc))
    description = "Kitchen faucet dripping steadily from the spout."
    kw = keyword_triage(description)
    assert kw == ("plumbing", "routine", "simple")  # heuristic alone says simple
    out = asyncio.run(node({"description": description}))
    assert out["trade"] == "plumbing"
    assert out["urgency"] == "routine"
    assert out["complexity"] == "standard"  # fallback forces full path


def test_node_hazard_trade_override_inv1() -> None:
    """VLM cannot classify away a keyword-detected hard-escalate trade."""
    vlm = _FixedTriageVLM(TriageResult(trade="hvac", urgency="routine", complexity="simple"))
    node = make_triage(vlm)
    out = asyncio.run(node({"description": "Smell of gas near the furnace closet"}))
    assert out["trade"] == "gas"
    # urgency floor also kicks in: "gas" is an emergency keyword
    assert out["urgency"] == "emergency"


def test_node_urgency_never_downgraded_below_keyword_floor() -> None:
    vlm = _FixedTriageVLM(TriageResult(trade="plumbing", urgency="routine", complexity="simple"))
    node = make_triage(vlm)
    out = asyncio.run(node({"description": "Active leak under the bathroom sink"}))
    assert out["urgency"] == "urgent"  # keyword floor: "leak"


def test_node_vlm_may_raise_urgency_above_keywords() -> None:
    vlm = _FixedTriageVLM(TriageResult(trade="hvac", urgency="urgent", complexity="standard"))
    node = make_triage(vlm)
    out = asyncio.run(node({"description": "Air handler making grinding noise"}))
    assert out["urgency"] == "urgent"  # keyword says routine; VLM upgrade stands


def test_node_preset_trade_wins() -> None:
    vlm = _FixedTriageVLM(TriageResult(trade="plumbing", urgency="routine", complexity="simple"))
    node = make_triage(vlm)
    out = asyncio.run(node({"description": "Dripping faucet", "trade": "appliance"}))
    assert out["trade"] == "appliance"


# ---------------------------------------------------------------------------
# Routing — only explicit "simple" takes the fast path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("complexity", "expected"),
    [
        ("simple", "retrieve_fast"),
        ("standard", "retrieve"),
        ("complex", "retrieve"),
        (None, "retrieve"),
    ],
)
def test_route_after_triage(complexity: str | None, expected: str) -> None:
    state: dict[str, Any] = {}
    if complexity is not None:
        state["complexity"] = complexity
    assert _route_after_triage(state) == expected


# ---------------------------------------------------------------------------
# keyword_triage heuristics
# ---------------------------------------------------------------------------


def test_keyword_triage_eval_004_is_simple() -> None:
    trade, urgency, complexity = keyword_triage(
        "Kitchen faucet dripping steadily from the spout. Everything else works fine."
    )
    assert (trade, urgency, complexity) == ("plumbing", "routine", "simple")


def test_keyword_triage_never_simple_when_not_routine() -> None:
    # "leak" → urgent, so the simple heuristic must not fire
    _, urgency, complexity = keyword_triage("Faucet leak dripping")
    assert urgency == "urgent"
    assert complexity == "standard"


def test_keyword_triage_long_description_not_simple() -> None:
    description = "faucet drip " + "word " * 30
    _, _, complexity = keyword_triage(description)
    assert complexity == "standard"


def test_keyword_triage_never_returns_complex() -> None:
    for text in ("gas smell everywhere", "flooded basement", "hvac dead", ""):
        _, _, complexity = keyword_triage(text)
        assert complexity in ("simple", "standard")


# ---------------------------------------------------------------------------
# Stub retrieval fast path — BM25-only, no rerank
# ---------------------------------------------------------------------------


class _SpyReranker:
    def __init__(self) -> None:
        self.called = False

    def rerank(self, query: str, candidates: list[Any], top_k: int = 5) -> list[Any]:
        self.called = True
        return candidates[:top_k]


class _NoopEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


def test_stub_fast_path_bm25_no_rerank() -> None:
    reranker = _SpyReranker()
    node = make_retrieve(_NoopEmbedder(), reranker, fast_path=True)
    out = asyncio.run(node({"description": "dripping faucet", "trade": "plumbing"}))
    assert len(out["evidence"]) == 5
    assert all(c["retrieval_stage"] == "bm25" for c in out["evidence"])
    assert reranker.called is False


def test_stub_full_path_reranks() -> None:
    reranker = _SpyReranker()
    node = make_retrieve(_NoopEmbedder(), reranker, fast_path=False)
    out = asyncio.run(node({"description": "dripping faucet", "trade": "plumbing"}))
    assert all(c["retrieval_stage"] == "fused" for c in out["evidence"])
    assert reranker.called is True
