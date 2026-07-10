"""Integration tests for ingestion — requires Qdrant."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from hero.adapters.stub_embedder import StubEmbedder
from hero.ingestion.ingest import COLLECTION_NAME, ingest_pdf

requires_qdrant = pytest.mark.skipif(
    not os.environ.get("QDRANT_URL"),
    reason="Set QDRANT_URL to run Qdrant integration tests",
)

TEST_PDF = str(Path(__file__).parent.parent / "fixtures" / "test_plumbing_manual.pdf")


@pytest.fixture
def clean_qdrant(qdrant_client: QdrantClient) -> QdrantClient:
    """Clean up the manuals collection before/after test."""
    collections = [c.name for c in qdrant_client.get_collections().collections]
    if COLLECTION_NAME in collections:
        qdrant_client.delete_collection(COLLECTION_NAME)
    yield qdrant_client
    # Cleanup after test
    collections = [c.name for c in qdrant_client.get_collections().collections]
    if COLLECTION_NAME in collections:
        qdrant_client.delete_collection(COLLECTION_NAME)


@requires_qdrant
def test_ingest_pdf_creates_collection(clean_qdrant: QdrantClient) -> None:
    """Ingesting a PDF should create the manuals collection."""
    embedder = StubEmbedder()
    count = ingest_pdf(
        pdf_path=TEST_PDF,
        doc_id="test-manual",
        manufacturer="ACME",
        model_codes=["PL-2000"],
        embedder=embedder,
        client=clean_qdrant,
    )
    assert count == 3  # 3 pages

    # Verify collection exists
    collections = [c.name for c in clean_qdrant.get_collections().collections]
    assert COLLECTION_NAME in collections

    # Verify points
    info = clean_qdrant.get_collection(COLLECTION_NAME)
    assert info.points_count == 3


@requires_qdrant
def test_ingest_is_idempotent(clean_qdrant: QdrantClient) -> None:
    """Re-ingesting the same PDF should not duplicate points."""
    embedder = StubEmbedder()
    for _ in range(2):
        ingest_pdf(
            pdf_path=TEST_PDF,
            doc_id="test-manual",
            manufacturer="ACME",
            model_codes=["PL-2000"],
            embedder=embedder,
            client=clean_qdrant,
        )
    info = clean_qdrant.get_collection(COLLECTION_NAME)
    assert info.points_count == 3  # not 6


@requires_qdrant
def test_ingested_points_have_correct_payload(clean_qdrant: QdrantClient) -> None:
    """Ingested points should have the expected payload fields."""
    embedder = StubEmbedder()
    ingest_pdf(
        pdf_path=TEST_PDF,
        doc_id="test-manual",
        manufacturer="ACME",
        model_codes=["PL-2000"],
        embedder=embedder,
        client=clean_qdrant,
    )
    # Scroll all points
    points, _ = clean_qdrant.scroll(
        collection_name=COLLECTION_NAME,
        limit=10,
        with_payload=True,
    )
    assert len(points) == 3
    for point in points:
        payload = point.payload
        assert payload is not None
        assert "doc_id" in payload
        assert payload["doc_id"] == "test-manual"
        assert "page" in payload
        assert "manufacturer" in payload
        assert payload["manufacturer"] == "ACME"
        assert "model_codes" in payload
        assert "text" in payload
        assert len(payload["text"]) > 0
