"""Nova turn engine (Phase 5 STEP 2, DEC-23/24).

One tenant message in → one NovaTurn out. Order of operations:

1. Guardrails (deterministic, no LLM — hero.nova.guardrails). Hazard →
   escalate with NO reply text; legal/medical/safety/injection → fixed copy.
2. Message cap (nova_max_messages): past it, fixed hand-off copy — no call.
3. Conversational tier via the VLM Protocol (interfaces/vlm.py — never an
   SDK call from here), with the HARD per-reply token cap.
4. Cost ceiling (nova_cost_ceiling_usd): per-ticket chat spend is LOGGED
   (WARNING) when breached — the token/message caps are the hard limits.

Stateless by design at STEP 2: the caller owns history + accumulated cost
(persistence is STEP 3's conversation_message table).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hero.config import Settings, get_settings
from hero.interfaces.vlm import VLM
from hero.nova.guardrails import check_message

logger = logging.getLogger(__name__)

# Same prompts-are-files rule as the pipeline adapters (CLAUDE.md conventions).
_NOVA_PROMPT = (Path(__file__).parent.parent / "prompts" / "nova.md").read_text()

# Fixed hand-off copy at the message cap — reviewed like code, never generated.
MESSAGE_CAP_REPLY = (
    "Thanks — I have everything I need for now. Your report is with the "
    "building team, and updates will appear right here."
)


@dataclass(frozen=True)
class NovaTurn:
    """Result of one conversational turn.

    - reply: model-generated text (guardrails passed, caps respected).
    - escalate: hazard — text is None; the surface shows its fixed escalation
      banner and the ticket goes to a human. Nothing conversational happens.
    - redirect: fixed guardrail copy (DEC-24 categories + injection).
    - capped: fixed hand-off copy (message cap reached).
    """

    kind: Literal["reply", "escalate", "redirect", "capped"]
    text: str | None
    guardrail_reason: str | None = None
    cost_usd: float = 0.0


async def nova_turn(
    vlm: VLM,
    *,
    history: list[dict[str, str]],
    message: str,
    conversation_cost_usd: float = 0.0,
    settings: Settings | None = None,
) -> NovaTurn:
    """Process one tenant message. `history` is prior {role, content} turns
    (user/assistant); `conversation_cost_usd` is the chat spend so far on
    this ticket (caller-accumulated until STEP 3 persists it)."""
    settings = settings or get_settings()

    decision = check_message(message)
    if decision.action == "escalate":
        # No conversational reply, ever — a human acts on hazards (INV-1 spirit).
        logger.warning("[NOVA] guardrail escalation (%s) — no reply generated", decision.reason)
        return NovaTurn(kind="escalate", text=None, guardrail_reason=decision.reason)
    if decision.action == "redirect":
        logger.info("[NOVA] guardrail redirect (%s)", decision.reason)
        return NovaTurn(kind="redirect", text=decision.reply, guardrail_reason=decision.reason)

    if len(history) >= settings.nova_max_messages:
        logger.warning(
            "[NOVA] message cap reached (%d >= %d) — returning hand-off copy",
            len(history),
            settings.nova_max_messages,
        )
        return NovaTurn(kind="capped", text=MESSAGE_CAP_REPLY)

    reply = await vlm.chat(
        system=_NOVA_PROMPT,
        messages=[*history, {"role": "user", "content": message}],
        max_tokens=settings.nova_max_reply_tokens,
    )

    total_cost = conversation_cost_usd + reply.cost_usd
    if total_cost > settings.nova_cost_ceiling_usd:
        # Logged, not blocking (DEC-23): the hard limits are the token and
        # message caps — this is the cost-envelope tripwire.
        logger.warning(
            "[NOVA] conversation cost $%.4f exceeds ceiling $%.2f (this turn $%.4f)",
            total_cost,
            settings.nova_cost_ceiling_usd,
            reply.cost_usd,
        )

    return NovaTurn(kind="reply", text=reply.text, cost_usd=reply.cost_usd)
