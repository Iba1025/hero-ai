"""Hybrid retrieval pipeline — dense MaxSim + BM25, RRF fusion (spec §7).

query → [dense: Qdrant MaxSim multivector, top 25] ┐
                                                    ├→ RRF (k=60) → top 50 → Reranker → top 5
query → [BM25 index, top 25]                        ┘

Fast path (complexity == "simple"): BM25-only top 5, no rerank.
Full path: the diagram above.
Both paths emit retrieval_stage on every chunk for eval attribution.
"""

from __future__ import annotations

from qdrant_client import QdrantClient

from hero.graph.state import EvidenceChunk
from hero.ingestion.ingest import COLLECTION_NAME, TOKENIZER_VERSION, text_to_sparse_vector
from hero.interfaces.embedder import Embedder
from hero.interfaces.reranker import Reranker
from hero.retrieval.integrity import IndexIntegrityError


def _check_payload_version(payload: dict[str, object]) -> None:
    """Query-time integrity check (P3-4 canary): reject stale-index chunks.

    Any returned point stamped with a different tokenizer/schema version
    (or none) means the index predates the running code — fail loudly
    rather than retrieve against it.
    """
    version = payload.get("tokenizer_version")
    if version != TOKENIZER_VERSION:
        raise IndexIntegrityError(
            f"retrieved point has tokenizer_version={version!r}, expected "
            f"{TOKENIZER_VERSION!r} — re-ingest {COLLECTION_NAME!r}"
        )


def _reciprocal_rank_fusion(
    *result_lists: list[EvidenceChunk],
    k: int = 60,
    top_n: int = 50,
) -> list[EvidenceChunk]:
    """Reciprocal Rank Fusion across multiple result lists.

    RRF score = Σ 1/(k + rank_i) for each list the doc appears in.
    """
    scores: dict[str, float] = {}
    chunks: dict[str, EvidenceChunk] = {}

    for results in result_lists:
        for rank, chunk in enumerate(results):
            key = f"{chunk.doc_id}:{chunk.page}"
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in chunks:
                chunks[key] = chunk

    # Sort by RRF score descending
    sorted_keys = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_n]

    return [
        chunks[key].model_copy(update={"score": scores[key], "retrieval_stage": "fused"})
        for key in sorted_keys
    ]


def retrieve_dense(
    query: str,
    embedder: Embedder,
    client: QdrantClient,
    top_k: int = 25,
) -> list[EvidenceChunk]:
    """Dense retrieval via Qdrant MaxSim multivector search."""
    query_vectors = embedder.embed_query(query)
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vectors,
        using="dense",
        limit=top_k,
        with_payload=True,
    )

    chunks: list[EvidenceChunk] = []
    for point in results.points:
        payload = point.payload or {}
        _check_payload_version(payload)
        chunks.append(
            EvidenceChunk(
                doc_id=str(payload.get("doc_id", "")),
                page=int(payload.get("page", 0)),
                score=float(point.score) if point.score else 0.0,
                retrieval_stage="dense",
                text=payload.get("text"),
            )
        )
    return chunks


def retrieve_bm25(
    query: str,
    client: QdrantClient,
    top_k: int = 25,
) -> list[EvidenceChunk]:
    """BM25 sparse vector retrieval via Qdrant."""
    sparse_query = text_to_sparse_vector(query)
    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=sparse_query,
        using="bm25",
        limit=top_k,
        with_payload=True,
    )

    chunks: list[EvidenceChunk] = []
    for point in results.points:
        payload = point.payload or {}
        _check_payload_version(payload)
        chunks.append(
            EvidenceChunk(
                doc_id=str(payload.get("doc_id", "")),
                page=int(payload.get("page", 0)),
                score=float(point.score) if point.score else 0.0,
                retrieval_stage="bm25",
                text=payload.get("text"),
            )
        )
    return chunks


def retrieve_hybrid(
    query: str,
    *,
    embedder: Embedder,
    reranker: Reranker,
    client: QdrantClient,
    fast_path: bool = False,
) -> list[EvidenceChunk]:
    """Full hybrid retrieval pipeline per spec §7.

    Fast path (complexity == "simple"): BM25-only top 5, no rerank.
    Full path: dense top-25 + BM25 top-25 → RRF → top-50 → Reranker → top-5.
    """
    if fast_path:
        bm25_results = retrieve_bm25(query, client, top_k=5)
        return bm25_results

    # Full path
    dense_results = retrieve_dense(query, embedder, client, top_k=25)
    bm25_results = retrieve_bm25(query, client, top_k=25)

    # RRF fusion
    fused = _reciprocal_rank_fusion(dense_results, bm25_results, k=60, top_n=50)

    # Reranker → top 5
    reranked = reranker.rerank(query, fused, top_k=5)

    return reranked
