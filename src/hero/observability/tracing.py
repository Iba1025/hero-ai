"""Langfuse node tracing (spec §11): span per graph node, trace per ticket.

- Span name = node name; all spans of a ticket share one deterministic
  trace id seeded from ticket_id, so a full pipeline run reads as one trace.
- Span metadata carries ticket_id + EMBEDDER_IMPL + RERANKER_IMPL
  (bake-off attribution, spec §11).
- Fully inert when LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY are unset: the
  original node function is returned untouched — zero wrapper overhead.
- The Langfuse SDK is imported lazily and only ever touched here; graph
  nodes stay SDK-free (DEC-1 spirit).
- Span outputs are compact scalar summaries of the node's state delta —
  never full evidence text or media (traces stay lean; media are pointers
  everywhere anyway, INV-3).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any

from hero.config import get_settings

logger = logging.getLogger(__name__)

_client: Any | None = None
_client_resolved = False


def _get_client() -> Any | None:
    """Lazy singleton Langfuse client; None when not configured."""
    global _client, _client_resolved
    if _client_resolved:
        return _client
    _client_resolved = True

    settings = get_settings()
    if not (
        settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key
    ):
        logger.info("[TRACE] Langfuse not configured — tracing disabled")
        return None

    from langfuse import Langfuse

    _client = Langfuse(
        host=settings.langfuse_host,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
    )
    logger.info("[TRACE] Langfuse tracing enabled (host=%s)", settings.langfuse_host)
    return _client


def _reset_client_for_tests() -> None:
    global _client, _client_resolved
    _client = None
    _client_resolved = False


def _summarize(delta: dict[str, Any]) -> dict[str, Any]:
    """Compact, scalar-only view of a node's state delta for span output."""
    out: dict[str, Any] = {}
    for key, value in delta.items():
        if isinstance(value, str | int | float | bool) or value is None:
            out[key] = value
        elif isinstance(value, list | dict):
            out[key] = f"<{type(value).__name__} len={len(value)}>"
        else:
            out[key] = f"<{type(value).__name__}>"
    return out


def _start_span(client: Any, name: str, state: dict[str, Any]) -> Any:
    settings = get_settings()
    ticket_id = str(state.get("ticket_id", ""))
    return client.start_span(
        name=name,
        trace_context={"trace_id": client.create_trace_id(seed=ticket_id)},
        input={"ticket_id": ticket_id},
        metadata={
            "ticket_id": ticket_id,
            "embedder_impl": settings.embedder_impl,
            "reranker_impl": settings.reranker_impl,
        },
    )


def traced_node(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a graph node (sync or async) in a Langfuse span.

    Returns `fn` unchanged when Langfuse is not configured. Exceptions
    (including LangGraph's interrupt) propagate untouched; the span is
    ended first so pauses/failures never leak unfinished spans.
    """
    if _get_client() is None:
        return fn

    if inspect.iscoroutinefunction(fn):

        async def async_wrapper(state: dict[str, Any]) -> dict[str, Any]:
            client = _get_client()
            span = _start_span(client, name, state)
            try:
                result: dict[str, Any] = await fn(state)
            except BaseException:
                span.end()
                raise
            span.update(output=_summarize(result))
            span.end()
            return result

        return async_wrapper

    def sync_wrapper(state: dict[str, Any]) -> dict[str, Any]:
        client = _get_client()
        span = _start_span(client, name, state)
        try:
            result: dict[str, Any] = fn(state)
        except BaseException:
            span.end()
            raise
        span.update(output=_summarize(result))
        span.end()
        return result

    return sync_wrapper


def flush() -> None:
    """Flush buffered spans (call at process shutdown / end of eval run)."""
    client = _get_client()
    if client is not None:
        client.flush()
