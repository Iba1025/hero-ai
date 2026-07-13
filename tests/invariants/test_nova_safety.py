"""INVARIANT: the Nova safety envelope is deterministic and hazard-silent.

Phase 5 STEP 2 (DEC-24), in the spirit of INV-1: safety is never gated by
confidence or by a model. Every hazard keyword the pipeline escalates on
(safety/hazards.py — the single source of truth) must make Nova escalate
with NO conversational reply, before any model is consulted. The guardrail
module must contain no LLM machinery at all.
"""

from __future__ import annotations

import inspect

import pytest

import hero.nova.guardrails as guardrails
from hero.interfaces.vlm import ChatReply
from hero.nova.chat import nova_turn
from hero.nova.guardrails import check_message
from hero.safety.hazards import HAZARD_KEYWORDS


@pytest.mark.parametrize("keyword", HAZARD_KEYWORDS)
def test_every_pipeline_hazard_keyword_escalates_in_chat(keyword: str) -> None:
    """Single source of truth: a keyword the pipeline escalates on can never
    be chatted about. Adding a keyword to safety/hazards.py extends Nova
    automatically — there is no second list to forget."""
    decision = check_message(f"there is {keyword} in my apartment")
    assert decision.action == "escalate"
    assert decision.reply is None


def test_guardrails_module_has_no_llm_imports() -> None:
    """Same rule as safety/: the pre-filter is pure functions + data."""
    source = inspect.getsource(guardrails)
    for banned in ("litellm", "openai", "anthropic", "interfaces.vlm", "adapters"):
        assert banned not in source, f"guardrails.py must not reference {banned!r}"


@pytest.mark.asyncio
async def test_hazard_never_reaches_the_model() -> None:
    """The conversational tier is unreachable for hazard messages — even a
    broken/malicious VLM cannot produce a reply to one."""

    class _ExplodingVLM:
        async def chat(
            self, *, system: str, messages: list[dict[str, str]], max_tokens: int
        ) -> ChatReply:
            raise AssertionError("chat tier consulted on a hazard message")

    from hero.config import Settings

    settings = Settings(database_url="postgresql+asyncpg://x/x")
    for keyword in HAZARD_KEYWORDS:
        turn = await nova_turn(
            _ExplodingVLM(),
            history=[],
            message=f"help, {keyword} in the kitchen",
            settings=settings,
        )
        assert turn.kind == "escalate"
        assert turn.text is None
