"""Observability — Langfuse tracing (spec §2/§11).

Self-hosted Langfuse only (INV-2: ca-central; ticket content never leaves
region). No-op when LANGFUSE_* config is absent — local dev and CI run
without a Langfuse instance and must not pay any tracing overhead.
"""

from hero.observability.tracing import flush, traced_node

__all__ = ["flush", "traced_node"]
