"""BM25 sparse tokenization must be process-stable (P3-3 regression).

The original implementation used builtin hash(), which is randomized per
process (PYTHONHASHSEED): sparse indices written at ingestion never matched
query-time indices, so BM25 silently returned zero results. The full path
masked it via dense+RRF; the BL-4 fast path (BM25-only) exposed it live
2026-07-10 — every fast-path ticket escalated with diagnosis_unparseable.
"""

from __future__ import annotations

import subprocess
import sys

from hero.ingestion.ingest import stable_token_index, text_to_sparse_vector


def test_stable_token_index_pinned_values() -> None:
    """Pinned values — fails if anyone switches back to builtin hash()."""
    assert stable_token_index("faucet") == 1677385273
    assert stable_token_index("cartridge") == 982861554


def test_stable_token_index_survives_hash_randomization() -> None:
    """Same token → same index in a fresh process with a different hash seed."""
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from hero.ingestion.ingest import stable_token_index;"
            "print(stable_token_index('faucet'))",
        ],
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": "12345", "PATH": "", "PYTHONPATH": "src"},
        check=True,
    )
    assert int(out.stdout.strip()) == stable_token_index("faucet")


def test_ingest_and_query_share_one_tokenizer() -> None:
    """Ingestion-side and query-side sparse vectors must be identical.

    retrieval/hybrid.py imports text_to_sparse_vector from ingestion —
    this guards against the tokenizer being re-duplicated and drifting.
    """
    from hero.retrieval import hybrid

    assert hybrid.text_to_sparse_vector is text_to_sparse_vector

    text = "Dripping faucet: replace cartridge FC-200-BR"
    a = text_to_sparse_vector(text)
    b = text_to_sparse_vector(text)
    assert a.indices == b.indices
    assert a.values == b.values
    assert len(a.indices) > 0
