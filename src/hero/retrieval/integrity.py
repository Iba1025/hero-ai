"""Index-integrity canary (P3-4 rider, after the BM25 dead-index incident).

Two independent guards, both loud:

1. Version stamp: every ingested point carries ``tokenizer_version`` in its
   payload. ``check_index_integrity`` fails if any point in the collection
   was written with a different (or missing) tokenizer version, and the
   query side rejects any returned chunk with a stale stamp.
2. Canary query: ``bm25_canary`` runs a real BM25 query for a term known to
   exist in the corpus and fails on zero results — the exact symptom of the
   2026-07-10 incident (builtin hash() randomization made every ingested
   sparse index unmatchable; dense+RRF masked it on the full path).

Call both wherever a Qdrant client is wired in (eval harness today; API
startup when retrieval lands there). Convention recorded in spec §11.
"""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from hero.ingestion.ingest import COLLECTION_NAME, TOKENIZER_VERSION


class IndexIntegrityError(Exception):
    """The Qdrant index does not match the running tokenizer/schema version."""


def check_index_integrity(client: QdrantClient) -> None:
    """Fail loudly if any point was ingested with a different tokenizer version.

    A point missing the stamp entirely (pre-canary ingestion) also fails —
    unstamped indices are exactly the ones that can be silently dead.
    """
    stale = client.count(
        COLLECTION_NAME,
        count_filter=Filter(
            must_not=[
                FieldCondition(key="tokenizer_version", match=MatchValue(value=TOKENIZER_VERSION))
            ]
        ),
        exact=True,
    ).count
    if stale > 0:
        raise IndexIntegrityError(
            f"{stale} point(s) in {COLLECTION_NAME!r} have tokenizer_version != "
            f"{TOKENIZER_VERSION!r} (or no stamp). Re-ingest before querying — "
            "BM25 results against a mismatched index are silently wrong."
        )


def bm25_canary(client: QdrantClient, term: str) -> None:
    """Fail loudly if a known-present term returns zero BM25 results.

    ``term`` must be a token guaranteed to occur in the ingested corpus
    (eval fixtures use "manual"). Zero results means the sparse index is
    dead end-to-end regardless of what the version stamp claims.
    """
    from hero.retrieval.hybrid import retrieve_bm25

    results = retrieve_bm25(term, client, top_k=1)
    if not results:
        raise IndexIntegrityError(
            f"BM25 canary query {term!r} returned zero results from "
            f"{COLLECTION_NAME!r} — the sparse index is not matching queries."
        )
