"""P3-4 Langfuse tracing — span per node, no-op when unconfigured.

The real Langfuse client needs a self-hosted instance (INV-2); unit tests
inject a fake client and verify the wrapper contract: identity passthrough
when disabled, span lifecycle (start → update → end) when enabled, and
span.end() on exceptions (LangGraph interrupts must not leak spans).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from hero.observability import tracing
from hero.observability.tracing import _summarize, traced_node


class _FakeSpan:
    def __init__(self, name: str, kwargs: dict[str, Any]) -> None:
        self.name = name
        self.kwargs = kwargs
        self.output: Any = None
        self.ended = False

    def update(self, output: Any = None, **_: Any) -> None:
        self.output = output

    def end(self) -> None:
        self.ended = True


class _FakeLangfuse:
    def __init__(self) -> None:
        self.spans: list[_FakeSpan] = []
        self.flushed = False

    def create_trace_id(self, *, seed: str) -> str:
        return f"trace-{seed}"

    def start_span(self, *, name: str, **kwargs: Any) -> _FakeSpan:
        span = _FakeSpan(name, kwargs)
        self.spans.append(span)
        return span

    def flush(self) -> None:
        self.flushed = True


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeLangfuse:
    client = _FakeLangfuse()
    monkeypatch.setattr(tracing, "_client", client)
    monkeypatch.setattr(tracing, "_client_resolved", True)
    return client


@pytest.fixture
def no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "_client", None)
    monkeypatch.setattr(tracing, "_client_resolved", True)


def test_unconfigured_returns_fn_unchanged(no_client: None) -> None:
    def node(state: dict[str, Any]) -> dict[str, Any]:
        return {}

    assert traced_node("intake", node) is node


def test_sync_node_span_lifecycle(fake_client: _FakeLangfuse) -> None:
    def node(state: dict[str, Any]) -> dict[str, Any]:
        return {"trade": "plumbing", "evidence": [1, 2, 3]}

    wrapped = traced_node("safety_gate", node)
    result = wrapped({"ticket_id": "t-1"})

    assert result["trade"] == "plumbing"
    (span,) = fake_client.spans
    assert span.name == "safety_gate"
    assert span.ended
    assert span.kwargs["trace_context"] == {"trace_id": "trace-t-1"}
    assert span.kwargs["metadata"]["ticket_id"] == "t-1"
    assert "embedder_impl" in span.kwargs["metadata"]
    assert "reranker_impl" in span.kwargs["metadata"]
    # output is summarized, not raw
    assert span.output == {"trade": "plumbing", "evidence": "<list len=3>"}


def test_async_node_span_lifecycle(fake_client: _FakeLangfuse) -> None:
    async def node(state: dict[str, Any]) -> dict[str, Any]:
        return {"complexity": "simple"}

    wrapped = traced_node("triage", node)
    result = asyncio.run(wrapped({"ticket_id": "t-2"}))

    assert result == {"complexity": "simple"}
    (span,) = fake_client.spans
    assert span.name == "triage"
    assert span.ended


def test_exception_ends_span_and_propagates(fake_client: _FakeLangfuse) -> None:
    """Interrupts/errors must not leak unfinished spans."""

    def node(state: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("interrupt-like")

    wrapped = traced_node("clarify", node)
    with pytest.raises(RuntimeError):
        wrapped({"ticket_id": "t-3"})
    (span,) = fake_client.spans
    assert span.ended
    assert span.output is None


def test_flush_drains_client(fake_client: _FakeLangfuse) -> None:
    tracing.flush()
    assert fake_client.flushed


def test_flush_noop_when_unconfigured(no_client: None) -> None:
    tracing.flush()  # must not raise


def test_summarize_scalars_and_containers() -> None:
    assert _summarize({"a": 1, "b": None, "c": {"x": 1}, "d": "s"}) == {
        "a": 1,
        "b": None,
        "c": "<dict len=1>",
        "d": "s",
    }
