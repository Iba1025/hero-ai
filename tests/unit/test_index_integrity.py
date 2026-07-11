"""P3-4 index-integrity canary — version stamp + BM25 canary (unit-level).

Qdrant is faked with minimal objects; the integration path runs in the
--live eval (check_index_integrity + bm25_canary before any ticket).
"""

from __future__ import annotations

from typing import Any

import pytest

from hero.ingestion.ingest import TOKENIZER_VERSION
from hero.retrieval.hybrid import _check_payload_version, retrieve_bm25
from hero.retrieval.integrity import IndexIntegrityError, bm25_canary, check_index_integrity


class _FakePoint:
    def __init__(self, payload: dict[str, Any], score: float = 1.0) -> None:
        self.payload = payload
        self.score = score


class _FakeQueryResult:
    def __init__(self, points: list[_FakePoint]) -> None:
        self.points = points


class _FakeCount:
    def __init__(self, count: int) -> None:
        self.count = count


class _FakeClient:
    def __init__(self, points: list[_FakePoint], stale_count: int = 0) -> None:
        self._points = points
        self._stale_count = stale_count

    def query_points(self, **kwargs: Any) -> _FakeQueryResult:
        return _FakeQueryResult(self._points)

    def count(self, *args: Any, **kwargs: Any) -> _FakeCount:
        return _FakeCount(self._stale_count)


def _payload(version: str | None = TOKENIZER_VERSION) -> dict[str, Any]:
    p: dict[str, Any] = {"doc_id": "test-manual", "page": 1, "text": "faucet"}
    if version is not None:
        p["tokenizer_version"] = version
    return p


def test_current_stamp_passes() -> None:
    _check_payload_version(_payload())


@pytest.mark.parametrize("version", ["old-hash-v0", None])
def test_stale_or_missing_stamp_raises(version: str | None) -> None:
    with pytest.raises(IndexIntegrityError):
        _check_payload_version(_payload(version))


def test_retrieve_bm25_rejects_stale_index() -> None:
    client = _FakeClient([_FakePoint(_payload("old-hash-v0"))])
    with pytest.raises(IndexIntegrityError):
        retrieve_bm25("dripping faucet", client, top_k=5)  # type: ignore[arg-type]


def test_retrieve_bm25_passes_current_index() -> None:
    client = _FakeClient([_FakePoint(_payload())])
    chunks = retrieve_bm25("dripping faucet", client, top_k=5)  # type: ignore[arg-type]
    assert len(chunks) == 1


def test_check_index_integrity_raises_on_stale_points() -> None:
    with pytest.raises(IndexIntegrityError):
        check_index_integrity(_FakeClient([], stale_count=2))  # type: ignore[arg-type]


def test_check_index_integrity_passes_clean() -> None:
    check_index_integrity(_FakeClient([], stale_count=0))  # type: ignore[arg-type]


def test_bm25_canary_raises_on_zero_results() -> None:
    with pytest.raises(IndexIntegrityError):
        bm25_canary(_FakeClient([]), "manual")  # type: ignore[arg-type]


def test_bm25_canary_passes_on_hit() -> None:
    bm25_canary(_FakeClient([_FakePoint(_payload())]), "manual")  # type: ignore[arg-type]
