"""Nova turn engine tests (Phase 5 STEP 2, DEC-23/24) — caps + guardrail wiring."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from hero.config import Settings
from hero.interfaces.vlm import ChatReply
from hero.nova.chat import MESSAGE_CAP_REPLY, nova_turn
from hero.nova.guardrails import REDIRECT_TENANCY_LEGAL


def _settings(**overrides: Any) -> Settings:
    return Settings(database_url="postgresql+asyncpg://x/x", **overrides)


class _FakeChatVLM:
    """Records chat calls; returns a fixed reply with a configurable cost."""

    def __init__(self, cost_usd: float = 0.0) -> None:
        self.calls: list[dict[str, Any]] = []
        self._cost = cost_usd

    async def chat(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> ChatReply:
        self.calls.append({"system": system, "messages": messages, "max_tokens": max_tokens})
        return ChatReply(text="Which fixture is it?", cost_usd=self._cost)


@pytest.mark.asyncio
async def test_allow_calls_chat_tier_with_hard_token_cap() -> None:
    vlm = _FakeChatVLM()
    settings = _settings(nova_max_reply_tokens=123)
    turn = await nova_turn(vlm, history=[], message="my sink is leaking", settings=settings)

    assert turn.kind == "reply"
    assert turn.text == "Which fixture is it?"
    assert len(vlm.calls) == 1
    call = vlm.calls[0]
    assert call["max_tokens"] == 123  # HARD cap forwarded to the provider
    assert "Nova" in call["system"]  # persona prompt loaded from prompts/nova.md
    assert call["messages"][-1] == {"role": "user", "content": "my sink is leaking"}


@pytest.mark.asyncio
async def test_hazard_escalates_without_model_call() -> None:
    vlm = _FakeChatVLM()
    turn = await nova_turn(vlm, history=[], message="I smell a gas leak", settings=_settings())
    assert turn.kind == "escalate"
    assert turn.text is None  # no conversational reply, ever
    assert turn.guardrail_reason == "hazard_keyword:gas leak"
    assert vlm.calls == []  # the model is NEVER consulted on a hazard


@pytest.mark.asyncio
async def test_redirect_returns_fixed_copy_without_model_call() -> None:
    vlm = _FakeChatVLM()
    turn = await nova_turn(vlm, history=[], message="can I withhold rent?", settings=_settings())
    assert turn.kind == "redirect"
    assert turn.text == REDIRECT_TENANCY_LEGAL
    assert vlm.calls == []


@pytest.mark.asyncio
async def test_message_cap_returns_handoff_copy_without_model_call() -> None:
    vlm = _FakeChatVLM()
    settings = _settings(nova_max_messages=4)
    history = [{"role": "user", "content": f"msg {i}"} for i in range(4)]
    turn = await nova_turn(vlm, history=history, message="one more thing", settings=settings)
    assert turn.kind == "capped"
    assert turn.text == MESSAGE_CAP_REPLY
    assert vlm.calls == []


@pytest.mark.asyncio
async def test_guardrails_run_before_message_cap() -> None:
    # A hazard on the capped-out turn still escalates — safety beats the cap.
    vlm = _FakeChatVLM()
    settings = _settings(nova_max_messages=1)
    history = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "ok"}]
    turn = await nova_turn(
        vlm, history=history, message="now there's flooding in the hall", settings=settings
    )
    assert turn.kind == "escalate"
    assert vlm.calls == []


@pytest.mark.asyncio
async def test_cost_ceiling_breach_is_logged_not_blocking(
    caplog: pytest.LogCaptureFixture,
) -> None:
    vlm = _FakeChatVLM(cost_usd=0.30)
    settings = _settings(nova_cost_ceiling_usd=0.25)
    with caplog.at_level(logging.WARNING, logger="hero.nova.chat"):
        turn = await nova_turn(
            vlm,
            history=[],
            message="the oven light is out",
            conversation_cost_usd=0.0,
            settings=settings,
        )
    assert turn.kind == "reply"  # ceiling logs, never blocks (DEC-23)
    assert turn.cost_usd == 0.30
    assert any("exceeds ceiling" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_cost_under_ceiling_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    vlm = _FakeChatVLM(cost_usd=0.01)
    with caplog.at_level(logging.WARNING, logger="hero.nova.chat"):
        await nova_turn(vlm, history=[], message="the oven light is out", settings=_settings())
    assert not any("exceeds ceiling" in r.message for r in caplog.records)
