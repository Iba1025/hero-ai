"""Qdrant ingestion CLI — PDF pages → embeddings → Qdrant upsert (spec §7).

Offline CLI job: PDF pages → images → Embedder.embed_page → Qdrant upsert.
Idempotent on (doc_id, page). Never runs in the request path (PRD §4.1).

Also generates BM25 sparse vectors from extracted text for hybrid retrieval.

Usage:
    uv run python -m hero.ingestion ingest <pdf> --manufacturer X --model-codes A,B
"""

from __future__ import annotations

import hashlib
import io
import re

import pypdfium2 as pdfium
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    MultiVectorComparator,
    MultiVectorConfig,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from hero.interfaces.embedder import Embedder

COLLECTION_NAME = "manuals"


def _extract_page_text(pdf_path: str, page_idx: int) -> str:
    """Extract text from a single PDF page."""
    doc = pdfium.PdfDocument(pdf_path)
    page = doc[page_idx]
    text: str = page.get_textpage().get_text_range()
    doc.close()
    return text


def _render_page_image(pdf_path: str, page_idx: int, scale: float = 2.0) -> bytes:
    """Render a PDF page to PNG image bytes."""
    doc = pdfium.PdfDocument(pdf_path)
    page = doc[page_idx]
    bitmap = page.render(scale=scale)
    pil_image = bitmap.to_pil()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    doc.close()
    return buf.getvalue()


def stable_token_index(token: str) -> int:
    """Stable 31-bit sparse index for a token.

    MUST be process-stable: builtin hash() is randomized per process
    (PYTHONHASHSEED), so indices written at ingestion time never matched
    query-time indices — BM25 silently returned zero results. Found live
    2026-07-10 when the BL-4 fast path (BM25-only) escalated every ticket
    with diagnosis_unparseable; the full path had masked it via dense+RRF.
    """
    digest = hashlib.sha1(token.encode()).digest()
    return int.from_bytes(digest[:4], "big") % (2**31)


def text_to_sparse_vector(text: str) -> SparseVector:
    """Convert text to a simple BM25-style sparse vector.

    Uses term frequency as weights. Qdrant sparse vectors are stored
    alongside dense multivectors in the same collection (spec §7:
    BM25 via Qdrant sparse vectors — do not add Elasticsearch).

    Shared by ingestion and query side (retrieval/hybrid.py) — the two
    MUST tokenize and index identically or BM25 matches nothing.
    """
    # Tokenize: lowercase, split on non-alphanumeric, filter short tokens
    tokens = re.findall(r"[a-z0-9][\w-]*", text.lower())
    # Count term frequencies
    tf: dict[str, int] = {}
    for token in tokens:
        tf[token] = tf.get(token, 0) + 1

    indices: list[int] = []
    values: list[float] = []
    for token, count in sorted(tf.items()):
        indices.append(stable_token_index(token))
        values.append(float(count))

    return SparseVector(indices=indices, values=values)


def _point_id(doc_id: str, page: int) -> str:
    """Deterministic point ID for idempotent upsert on (doc_id, page)."""
    raw = f"{doc_id}:{page}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def ensure_collection(client: QdrantClient, vector_dim: int) -> None:
    """Create or verify the manuals collection with multivector + sparse config."""
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in collections:
        return

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": VectorParams(
                size=vector_dim,
                distance=Distance.COSINE,
                multivector_config=MultiVectorConfig(
                    comparator=MultiVectorComparator.MAX_SIM,
                ),
            ),
        },
        sparse_vectors_config={
            "bm25": SparseVectorParams(
                index=SparseIndexParams(on_disk=False),
            ),
        },
    )


def ingest_pdf(
    *,
    pdf_path: str,
    doc_id: str,
    manufacturer: str,
    model_codes: list[str],
    embedder: Embedder,
    client: QdrantClient,
    batch_size: int = 4,
) -> int:
    """Ingest a PDF into Qdrant. Returns number of pages ingested.

    Idempotent on (doc_id, page) — re-running overwrites with same point IDs.
    """
    doc = pdfium.PdfDocument(pdf_path)
    n_pages = len(doc)
    doc.close()

    # First, embed one page to get vector dim and ensure collection exists
    first_image = _render_page_image(pdf_path, 0)
    first_vectors = embedder.embed_page(first_image)
    vector_dim = len(first_vectors[0])
    ensure_collection(client, vector_dim)

    # Process pages in batches
    total_ingested = 0
    for batch_start in range(0, n_pages, batch_size):
        batch_end = min(batch_start + batch_size, n_pages)
        page_indices = list(range(batch_start, batch_end))

        # Render images
        images = [_render_page_image(pdf_path, i) for i in page_indices]

        # Embed (batch if available, else one-by-one)
        if hasattr(embedder, "embed_pages_batch"):
            all_vectors = embedder.embed_pages_batch(images)
        else:
            all_vectors = [embedder.embed_page(img) for img in images]

        # Build points
        points: list[PointStruct] = []
        for i, page_idx in enumerate(page_indices):
            text = _extract_page_text(pdf_path, page_idx)
            sparse = text_to_sparse_vector(text)
            point_id = _point_id(doc_id, page_idx)

            points.append(
                PointStruct(
                    id=point_id,
                    vector={
                        "dense": all_vectors[i],
                        "bm25": sparse,
                    },
                    payload={
                        "doc_id": doc_id,
                        "page": page_idx,
                        "manufacturer": manufacturer,
                        "model_codes": model_codes,
                        "text": text,  # stored for reranker input
                    },
                )
            )

        client.upsert(collection_name=COLLECTION_NAME, points=points)
        total_ingested += len(points)

    return total_ingested
