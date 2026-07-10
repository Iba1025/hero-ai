"""Real-model hybrid retrieval trace — phase-close evidence, run locally only.

Ingests the test fixture PDF with the REAL ColModernVBERT embedder, then runs
the full hybrid path (dense + BM25 -> RRF -> REAL BGE rerank) against a real
Qdrant server, printing every stage so rerank reordering is observable.

Requires: local Qdrant on QDRANT_URL, HF model downloads (~GBs), no API keys.

Usage:
    QDRANT_URL=http://localhost:6333 uv run python scripts/trace_hybrid_real.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from hero.ingestion.ingest import COLLECTION_NAME, ingest_pdf
from hero.retrieval.hybrid import (
    _reciprocal_rank_fusion,
    retrieve_bm25,
    retrieve_dense,
)

TEST_PDF = str(Path(__file__).parent.parent / "tests" / "fixtures" / "test_plumbing_manual.pdf")
QUERY = "P-trap installation PT-100-SS"


def _print_chunks(label: str, chunks: list) -> None:  # type: ignore[type-arg]
    print(f"\n  [{label}] {len(chunks)} results:")
    for i, c in enumerate(chunks):
        print(
            f"    #{i + 1}: doc_id={c.doc_id} page={c.page}"
            f" score={c.score:.6f} stage={c.retrieval_stage}"
        )


def main() -> int:
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    client = QdrantClient(url=url, timeout=30)
    print(f"Qdrant: {url} — {client.get_collections()!r}")

    # --- Load real models (timed) ---
    t0 = time.monotonic()
    from hero.adapters.colmodernvbert import ColModernVBertEmbedder

    embedder = ColModernVBertEmbedder()
    t_embedder_load = time.monotonic() - t0
    print(f"\n[LOAD] ColModernVBertEmbedder ({embedder.model_id}): {t_embedder_load:.1f}s")

    t0 = time.monotonic()
    from hero.adapters.bge_reranker import BGEReranker

    reranker = BGEReranker()
    t_reranker_load = time.monotonic() - t0
    print(f"[LOAD] BGEReranker (BAAI/bge-reranker-v2-m3): {t_reranker_load:.1f}s")

    # --- Ingest fixture PDF with REAL embedder (timed) ---
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in collections:
        client.delete_collection(COLLECTION_NAME)
    t0 = time.monotonic()
    count = ingest_pdf(
        pdf_path=TEST_PDF,
        doc_id="test-manual",
        manufacturer="ACME",
        model_codes=["PL-2000"],
        embedder=embedder,
        client=client,
    )
    t_ingest = time.monotonic() - t0
    print(f"[INGEST] {count} pages with real embedder: {t_ingest:.1f}s")

    _run_stages(client, embedder, reranker)

    # Reordering demo: with a 3-page corpus, the primary query's fused order
    # already matches relevance, so rerank has nothing to fix. These queries
    # naturally produce fused orders that BGE corrects on real page text.
    print(f"\n{'#' * 66}")
    print("### RERANK REORDERING DEMO — queries where fusion order != relevance")
    print(f"{'#' * 66}")
    for q in ("leak under sink troubleshooting steps", "how to fix a dripping faucet"):
        dense = retrieve_dense(q, embedder, client, top_k=25)
        bm25 = retrieve_bm25(q, client, top_k=25)
        fused = _reciprocal_rank_fusion(dense, bm25, k=60, top_n=50)
        reranked = reranker.rerank(q, fused, top_k=5)
        print(f"\n  QUERY: {q!r}")
        _print_chunks("FUSED (RRF)", fused)
        _print_chunks("RERANKED (real BGE)", reranked)
        fo = [(c.doc_id, c.page) for c in fused[:5]]
        ro = [(c.doc_id, c.page) for c in reranked]
        print(f"\n  fused order:    {fo}")
        print(f"  reranked order: {ro}")
        print(f"  REORDERED: {fo != ro}")

    return 0


def _run_stages(client: QdrantClient, embedder: Any, reranker: Any) -> None:
    for run in ("COLD", "WARM"):
        print(f"\n{'=' * 66}")
        print(f"=== {run} RUN — FULL HYBRID: {QUERY!r} (real embedder + real BGE) ===")
        print(f"{'=' * 66}")

        t0 = time.monotonic()
        dense = retrieve_dense(QUERY, embedder, client, top_k=25)
        t_dense = time.monotonic() - t0
        _print_chunks(f"STAGE 1 — DENSE (Qdrant MaxSim, real ColModernVBERT) {t_dense:.3f}s", dense)

        t0 = time.monotonic()
        bm25 = retrieve_bm25(QUERY, client, top_k=25)
        t_bm25 = time.monotonic() - t0
        _print_chunks(f"STAGE 2 — BM25 (Qdrant sparse) {t_bm25:.3f}s", bm25)

        t0 = time.monotonic()
        fused = _reciprocal_rank_fusion(dense, bm25, k=60, top_n=50)
        t_rrf = time.monotonic() - t0
        _print_chunks(f"STAGE 3 — RRF (k=60) {t_rrf * 1000:.1f}ms", fused)

        t0 = time.monotonic()
        reranked = reranker.rerank(QUERY, fused, top_k=5)
        t_rerank = time.monotonic() - t0
        _print_chunks(f"STAGE 4 — RERANKED (REAL BGE cross-encoder) {t_rerank:.3f}s", reranked)

        fused_order = [(c.doc_id, c.page) for c in fused[:5]]
        reranked_order = [(c.doc_id, c.page) for c in reranked]
        print(f"\n  fused order (top5):    {fused_order}")
        print(f"  reranked order (top5): {reranked_order}")
        print(f"  REORDERED: {fused_order != reranked_order}")
        print(
            f"  latency: dense={t_dense:.3f}s bm25={t_bm25:.3f}s "
            f"rrf={t_rrf * 1000:.1f}ms rerank={t_rerank:.3f}s"
        )


if __name__ == "__main__":
    sys.exit(main())
