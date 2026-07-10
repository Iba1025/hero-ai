"""Integration tests for hybrid retrieval — requires Qdrant with ingested data."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.ingestion.ingest import COLLECTION_NAME, ingest_pdf
from hero.retrieval.hybrid import (
    retrieve_bm25,
    retrieve_dense,
    retrieve_hybrid,
)

requires_qdrant = pytest.mark.skipif(
    not os.environ.get("QDRANT_URL"),
    reason="Set QDRANT_URL to run Qdrant integration tests",
)

TEST_PDF = str(Path(__file__).parent.parent / "fixtures" / "test_plumbing_manual.pdf")


@pytest.fixture(scope="module")
def ingested_qdrant() -> QdrantClient:
    """Ingest test PDF into Qdrant for retrieval tests."""
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    client = QdrantClient(url=url, timeout=10)

    # Clean and ingest
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in collections:
        client.delete_collection(COLLECTION_NAME)

    embedder = StubEmbedder()
    ingest_pdf(
        pdf_path=TEST_PDF,
        doc_id="test-manual",
        manufacturer="ACME",
        model_codes=["PL-2000"],
        embedder=embedder,
        client=client,
    )
    yield client

    # Cleanup
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in collections:
        client.delete_collection(COLLECTION_NAME)


@requires_qdrant
def test_bm25_retrieves_by_part_number(ingested_qdrant: QdrantClient) -> None:
    """BM25 should find pages containing a specific part number."""
    results = retrieve_bm25("PT-100-SS", ingested_qdrant, top_k=5)
    assert len(results) >= 1
    assert all(c.retrieval_stage == "bm25" for c in results)
    # PT-100-SS appears on pages 0 and 2 of the test PDF
    pages_found = {c.page for c in results}
    assert 0 in pages_found or 2 in pages_found


@requires_qdrant
def test_dense_retrieves_semantically(ingested_qdrant: QdrantClient) -> None:
    """Dense retrieval should return results for a semantic query."""
    embedder = StubEmbedder()
    results = retrieve_dense("leaking pipe under sink", embedder, ingested_qdrant, top_k=5)
    assert len(results) >= 1
    assert all(c.retrieval_stage == "dense" for c in results)


@requires_qdrant
def test_hybrid_retrieval_full_path(ingested_qdrant: QdrantClient) -> None:
    """Full-path hybrid retrieval should return reranked results."""
    embedder = StubEmbedder()
    reranker = StubReranker()
    results = retrieve_hybrid(
        "P-trap installation PT-100-SS",
        embedder=embedder,
        reranker=reranker,
        client=ingested_qdrant,
        fast_path=False,
    )
    assert len(results) >= 1
    assert all(c.retrieval_stage == "reranked" for c in results)


@requires_qdrant
def test_hybrid_retrieval_fast_path(ingested_qdrant: QdrantClient) -> None:
    """Fast-path retrieval should use BM25 only (no dense, no rerank)."""
    results = retrieve_hybrid(
        "PT-100-SS",
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        client=ingested_qdrant,
        fast_path=True,
    )
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
