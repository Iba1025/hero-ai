"""Non-destructive staged retrieval probe against the LIVE manuals collection.

Unlike trace_hybrid_real.py this never deletes or ingests anything — it runs
the integrity canary, then prints dense / BM25 / RRF / reranked results for
each query with a page-text snippet, so citation quality (troubleshooting vs
TOC/boilerplate pages) is visible per corpus document.

Usage:
    uv run python scripts/probe_retrieval.py "query one" "query two" ...
"""

from __future__ import annotations

import os
import re
import sys
import time

from qdrant_client import QdrantClient

from hero.retrieval.hybrid import (
    _reciprocal_rank_fusion,
    retrieve_bm25,
    retrieve_dense,
)
from hero.retrieval.integrity import bm25_canary, check_index_integrity

SNIPPET_CHARS = 90


def _snippet(text: str | None) -> str:
    if not text:
        return "<no text payload>"
    return re.sub(r"\s+", " ", text).strip()[:SNIPPET_CHARS]


def _print_chunks(label: str, chunks: list) -> None:  # type: ignore[type-arg]
    print(f"\n  [{label}] top {len(chunks)}:")
    for i, c in enumerate(chunks):
        print(f"    #{i + 1}: {c.doc_id} p.{c.page + 1} score={c.score:.4f}")
        print(f"         {_snippet(c.text)}")


def main() -> int:
    queries = sys.argv[1:]
    if not queries:
        print("usage: probe_retrieval.py <query> [<query> ...]")
        return 1

    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    client = QdrantClient(url=url, timeout=30)

    print("== integrity canary ==")
    check_index_integrity(client)
    bm25_canary(client, "manual")
    print("check_index_integrity: OK (all stamps current)")
    print("bm25_canary('manual'): OK (sparse index live)")

    t0 = time.monotonic()
    from hero.adapters.colmodernvbert import ColModernVBertEmbedder

    embedder = ColModernVBertEmbedder()
    print(f"\n[LOAD] embedder: {time.monotonic() - t0:.1f}s")
    t0 = time.monotonic()
    from hero.adapters.bge_reranker import BGEReranker

    reranker = BGEReranker()
    print(f"[LOAD] reranker: {time.monotonic() - t0:.1f}s")

    for q in queries:
        print(f"\n{'=' * 72}\nQUERY: {q!r}\n{'=' * 72}")
        dense = retrieve_dense(q, embedder, client, top_k=25)
        bm25 = retrieve_bm25(q, client, top_k=25)
        fused = _reciprocal_rank_fusion(dense, bm25, k=60, top_n=50)
        reranked = reranker.rerank(q, fused, top_k=5)
        _print_chunks("STAGE 1 dense", dense[:5])
        _print_chunks("STAGE 2 bm25", bm25[:5])
        _print_chunks("STAGE 3 fused (RRF)", fused[:5])
        _print_chunks("STAGE 4 reranked (BGE)", reranked)

    return 0


if __name__ == "__main__":
    sys.exit(main())
