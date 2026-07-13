"""Single resume path rule (P4-4 hardening, spec §4).

Any Command(resume=...) through the API graph must go through
hero.api.resume.resume_with_answer — the only path that snapshots the
pending question and writes the clarify_answered ledger round. An
out-of-path resume fails loudly, so a ledger can never silently lose
the question.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from langgraph.types import Command

from hero.api import pipeline as pipeline_mod
from hero.api import resume as resume_mod
from hero.api.deps import _ResumeGuardedGraph
from hero.api.resume import (
    NotAwaitingClarificationError,
    ResumeNotAllowedError,
    resume_with_answer,
)

pytestmark = pytest.mark.asyncio


class _FakeStateSnapshot:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values


class _FakeGraph:
    """Records invocations; returns a canned post-resume state."""

    def __init__(
        self,
        *,
        pending_question: str | None = "Which unit?",
        result: dict[str, Any] | None = None,
    ) -> None:
        self._pending = pending_question
        self._result = result or {"clarify_rounds": 1, "trade": "hvac"}
        self.invocations: list[Any] = []

    async def aget_state(self, config: dict[str, Any]) -> _FakeStateSnapshot:
        values = {"pending_question": self._pending} if self._pending else {"trade": "hvac"}
        return _FakeStateSnapshot(values)

    async def ainvoke(self, run_input: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.invocations.append(run_input)
        return self._result


async def test_out_of_path_resume_fails_loudly() -> None:
    """A raw Command(resume=...) against the API graph raises — never runs."""
    inner = _FakeGraph()
    guarded = _ResumeGuardedGraph(inner)
    with pytest.raises(ResumeNotAllowedError):
        await guarded.ainvoke(Command(resume="the answer"), config={})
    assert inner.invocations == []  # the resume never reached the graph


async def test_guard_passes_plain_input_through() -> None:
    """Normal create-run invocations (dict input) are untouched."""
    inner = _FakeGraph()
    guarded = _ResumeGuardedGraph(inner)
    result = await guarded.ainvoke({"ticket_id": "t-1"}, config={})
    assert result["trade"] == "hvac"
    assert inner.invocations == [{"ticket_id": "t-1"}]


async def test_guard_delegates_other_attributes() -> None:
    guarded = _ResumeGuardedGraph(_FakeGraph())
    snapshot = await guarded.aget_state({})
    assert snapshot.values["pending_question"] == "Which unit?"


async def test_sanctioned_resume_records_the_question(monkeypatch: pytest.MonkeyPatch) -> None:
    """resume_with_answer through the guarded graph: allowed, and the ledger
    round carries the question snapshotted before the resume."""
    appended: list[tuple[str, dict[str, Any]]] = []

    async def fake_append(session: Any, *, ticket_id: Any, run_id: str, events: Any) -> None:
        appended.extend(events)

    async def fake_persist_completion(
        session: Any, *, ticket_id: Any, run_id: str, result: Any
    ) -> str:
        return "diagnosed"

    monkeypatch.setattr(resume_mod, "append_ticket_events", fake_append)
    # resume_with_answer imports persist_completion from hero.api.pipeline at
    # call time — patch it at its home module (BL-17: shared completion path).
    monkeypatch.setattr(pipeline_mod, "persist_completion", fake_persist_completion)

    class _FakeSession:
        async def commit(self) -> None:
            pass

    guarded = _ResumeGuardedGraph(_FakeGraph(pending_question="Which unit?"))
    result = await resume_with_answer(
        guarded,
        _FakeSession(),  # type: ignore[arg-type]
        ticket_id=uuid.uuid4(),
        answer="Unit 4B",
    )
    assert result["trade"] == "hvac"
    assert appended[0][0] == "clarify_answered"
    assert appended[0][1]["question"] == "Which unit?"
    assert appended[0][1]["answer"] == "Unit 4B"


async def test_resume_without_pending_question_rejected() -> None:
    guarded = _ResumeGuardedGraph(_FakeGraph(pending_question=None))

    class _FakeSession:
        async def commit(self) -> None:
            pass

    with pytest.raises(NotAwaitingClarificationError):
        await resume_with_answer(
            guarded,
            _FakeSession(),  # type: ignore[arg-type]
            ticket_id=uuid.uuid4(),
            answer="nobody asked",
        )
