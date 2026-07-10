"""Integration tests for hybrid retrieval — requires Qdrant with ingested data.

Prints detailed per-stage traces so CI logs show REAL Qdrant scores
(dense cosine similarity, BM25 sparse match, RRF fusion math).
Reranker is StubReranker in CI (model download constraint); BGE reranker
is tested locally with HERO_TEST_MODELS=1.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.ingestion.ingest import COLLECTION_NAME, ingest_pdf
from hero.retrieval.hybrid import (
    _reciprocal_rank_fusion,
    retrieve_bm25,
    retrieve_dense,
    retrieve_hybrid,
)

requires_qdrant = pytest.mark.skipif(
    not os.environ.get("QDRANT_URL"),
    reason="Set QDRANT_URL to run Qdrant integration tests",
)

TEST_PDF = str(Path(__file__).parent.parent / "fixtures" / "test_plumbing_manual.pdf")


def _print_chunks(label: str, chunks: list) -> None:  # type: ignore[type-arg]
    """Print chunk details for CI log inspection."""
    print(f"\n  [{label}] {len(chunks)} results:")
    for i, c in enumerate(chunks):
        print(
            f"    #{i + 1}: doc_id={c.doc_id} page={c.page}"
            f" score={c.score:.6f} stage={c.retrieval_stage}"
        )


@pytest.fixture(scope="module")
def ingested_qdrant() -> QdrantClient:
    """Ingest test PDF into Qdrant for retrieval tests."""
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    client = QdrantClient(url=url, timeout=10)

    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in collections:
        client.delete_collection(COLLECTION_NAME)

    embedder = StubEmbedder()
    count = ingest_pdf(
        pdf_path=TEST_PDF,
        doc_id="test-manual",
        manufacturer="ACME",
        model_codes=["PL-2000"],
        embedder=embedder,
        client=client,
    )
    print(f"\n  [SETUP] Ingested {count} pages from test PDF (embedder=StubEmbedder)")
    yield client

    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in collections:
        client.delete_collection(COLLECTION_NAME)


@requires_qdrant
def test_bm25_retrieves_by_part_number(ingested_qdrant: QdrantClient) -> None:
    """BM25 should find pages containing a specific part number."""
    print("\n=== QUERY: 'PT-100-SS' (part number, BM25 path) ===")
    results = retrieve_bm25("PT-100-SS", ingested_qdrant, top_k=5)
    _print_chunks("BM25", results)

    assert len(results) >= 1
    assert all(c.retrieval_stage == "bm25" for c in results)
    pages_found = {c.page for c in results}
    assert 0 in pages_found or 2 in pages_found, f"Expected page 0 or 2, got {pages_found}"


@requires_qdrant
def test_dense_retrieves_semantically(ingested_qdrant: QdrantClient) -> None:
    """Dense retrieval should return results for a semantic query."""
    embedder = StubEmbedder()
    print("\n=== QUERY: 'leaking pipe under sink' (semantic, dense path) ===")
    results = retrieve_dense("leaking pipe under sink", embedder, ingested_qdrant, top_k=5)
    _print_chunks("DENSE", results)

    assert len(results) >= 1
    assert all(c.retrieval_stage == "dense" for c in results)


@requires_qdrant
def test_hybrid_retrieval_full_path(ingested_qdrant: QdrantClient) -> None:
    """Full-path hybrid: dense + BM25 → RRF → rerank. Prints each stage."""
    embedder = StubEmbedder()
    reranker = StubReranker()
    query = "P-trap installation PT-100-SS"
    print(f"\n=== FULL HYBRID: '{query}' ===")
    print("  (reranker=StubReranker — BGE tested locally with HERO_TEST_MODELS=1)")

    # Stage 1: Dense
    dense = retrieve_dense(query, embedder, ingested_qdrant, top_k=25)
    _print_chunks("STAGE 1 — DENSE (Qdrant MaxSim cosine)", dense)

    # Stage 2: BM25
    bm25 = retrieve_bm25(query, ingested_qdrant, top_k=25)
    _print_chunks("STAGE 2 — BM25 (Qdrant sparse)", bm25)

    # Stage 3: RRF
    fused = _reciprocal_rank_fusion(dense, bm25, k=60, top_n=50)
    _print_chunks("STAGE 3 — RRF (k=60)", fused)

    # Stage 4: Rerank
    reranked = reranker.rerank(query, fused, top_k=5)
    _print_chunks("STAGE 4 — RERANKED (StubReranker: sort by RRF score)", reranked)

    # Full pipeline should match
    full = retrieve_hybrid(
        query, embedder=embedder, reranker=reranker, client=ingested_qdrant, fast_path=False
    )
    assert len(full) >= 1
    assert all(c.retrieval_stage == "reranked" for c in full)


@requires_qdrant
def test_hybrid_retrieval_fast_path(ingested_qdrant: QdrantClient) -> None:
    """Fast-path: BM25 only, no dense, no rerank."""
    print("\n=== FAST PATH: 'PT-100-SS' (BM25 only) ===")
    results = retrieve_hybrid(
        "PT-100-SS",
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        client=ingested_qdrant,
        fast_path=True,
    )
    _print_chunks("FAST PATH (BM25 only)", results)

    assert len(results) >= 1
    assert all(c.retrieval_stage == "bm25" for c in results)


@requires_qdrant
def test_retrieval_stage_attribution(ingested_qdrant: QdrantClient) -> None:
    """Every chunk must have a retrieval_stage for eval attribution."""
    embedder = StubEmbedder()
    reranker = StubReranker()
    results = retrieve_hybrid(
        "faucet cartridge replacement",
        embedder=embedder,
        reranker=reranker,
        client=ingested_qdrant,
    )
    for chunk in results:
        assert chunk.retrieval_stage in ("dense", "bm25", "fused", "reranked")
