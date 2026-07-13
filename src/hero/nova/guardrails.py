"""Nova guardrails — deterministic, no-LLM pre-filter (Phase 5 STEP 2, DEC-24).

EVERY tenant message passes through check_message() BEFORE any conversational
model call. Precedence (first match wins):

1. Hazard keywords (reused from hero.safety.hazards — single source of truth)
   → instant escalation, NO conversational reply. Chatting about a gas smell
   is the same anti-pattern as clarifying one (P4-5b): a human acts.
2. Prompt-injection markers → fixed off-topic redirect. Deterministic first
   layer; the nova.md persona is the model-side second layer (live-tested
   in nova_evals).
3. Legal / tenancy-rights, medical, and safety-advice questions → fixed
   redirect copy (DEC-24: Nova NEVER answers these).

Pattern lists are data reviewed like code (same rule as safety/hazards.py).
NO LLM imports anywhere in this module — pure functions, INV-1 spirit:
nothing here is gated by confidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from hero.safety.hazards import HAZARD_KEYWORDS

GuardrailAction = Literal["allow", "escalate", "redirect"]


@dataclass(frozen=True)
class GuardrailDecision:
    """Outcome of the deterministic pre-filter for one tenant message.

    - allow: message may proceed to the conversational tier.
    - escalate: hazard detected — NO reply text; the caller escalates the
      ticket to a human immediately (reply rendering is the surface's fixed
      escalation banner, never generated copy).
    - redirect: fixed copy in `reply`; the model is not called.
    """

    action: GuardrailAction
    reason: str | None = None
    reply: str | None = None


# ── Fixed redirect copy (DEC-24) — reviewed like code, never generated ──────

REDIRECT_TENANCY_LEGAL = (
    "I can't help with legal or tenancy questions — I can only take maintenance "
    "reports for the building team. For rights or lease questions, please contact "
    "your property manager or a local tenant resource. Is there a problem in your "
    "unit I can log?"
)

REDIRECT_MEDICAL = (
    "I can't give medical advice. If anyone is hurt or feeling unwell, please "
    "call 911 or your local emergency line right away. If something in your unit "
    "may be causing it, tell me what you've noticed and I'll log it for the "
    "building team."
)

REDIRECT_SAFETY_ADVICE = (
    "I can't advise on whether something is safe. If you think there's any "
    "immediate danger, leave the area and call 911 or your building's emergency "
    "line, and contact your building team directly. I can log the details of "
    "what you're seeing — what's happening?"
)

REDIRECT_OFF_TOPIC = (
    "I can only help with reporting a maintenance problem in your unit or "
    "building. What's happening with the property?"
)


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p) for p in patterns]


# Prompt-injection markers. Deliberately narrow: a false positive costs one
# fixed redirect line, a false negative reaches the persona's second layer.
_INJECTION_PATTERNS = _compile(
    [
        r"ignore (?:\w+ ){0,3}instructions",
        r"disregard (?:\w+ ){0,3}instructions",
        r"forget (?:\w+ ){0,3}instructions",
        r"new instructions\b",
        r"system prompt",
        r"developer mode",
        r"\bjailbreak\b",
        r"you are now\b",
        r"pretend (?:you are|you're|to be)\b",
        r"\broleplay\b",
        r"repeat (?:\w+ ){0,3}(?:prompt|instructions)",
    ]
)

_TENANCY_LEGAL_PATTERNS = _compile(
    [
        r"withhold(?:ing)? (?:my |the )?rent",
        r"rent strike",
        r"(?:tenant|tenancy|renters?) rights",
        r"my rights as a tenant",
        r"landlord[- ](?:and[- ])?tenant board",
        r"\bltb\b",
        r"\bevict\w*",
        r"\bsue\b|\blawsuit\b|\blawyer\b|legal action|small claims",
        r"break(?:ing)? (?:my |the )?lease",
        r"rent (?:reduction|abatement)",
        r"\bcompensat\w+|\breimburs\w+",
    ]
)

_MEDICAL_PATTERNS = _compile(
    [
        r"\bdizzy\b|\bdizziness\b",
        r"\bheadaches?\b",
        r"\bnausea\b|\bnauseous\b|\bvomit\w*",
        r"trouble breathing|difficulty breathing|short(?:ness)? of breath",
        r"chest pain",
        r"passed out|\bunconscious\b|\bfaint(?:ed|ing)?\b",
        r"\bbleeding\b|\binjur\w+",
        r"\bpoison\w*",
        r"\brash\b|\ballerg\w+",
        r"medical advice",
        r"should i (?:see a doctor|go to the hospital)",
        r"what should i take (?:for|to)\b",
    ]
)

_SAFETY_ADVICE_PATTERNS = _compile(
    [
        r"\bis (?:it|this|that|the [\w ]{1,20}?) (?:safe|dangerous|risky|toxic)\b",
        r"safe to (?:use|stay|sleep|touch|turn|breathe|drink)",
        r"should (?:i|we) (?:evacuate|leave|be worried|be concerned|be scared)",
        r"(?:is it|am i|are we) in danger",
        r"\bhazardous\b",
    ]
)


def check_message(text: str) -> GuardrailDecision:
    """Deterministic pre-filter for one tenant message. Pure function, no LLM.

    Hazards are checked FIRST: "is the gas smell dangerous?" escalates (a
    human acts) rather than getting the safety-advice redirect.
    """
    lowered = text.lower()

    for kw in HAZARD_KEYWORDS:
        if kw in lowered:
            return GuardrailDecision(action="escalate", reason=f"hazard_keyword:{kw}")

    for pattern in _INJECTION_PATTERNS:
        m = pattern.search(lowered)
        if m:
            return GuardrailDecision(
                action="redirect",
                reason=f"injection:{m.group(0)}",
                reply=REDIRECT_OFF_TOPIC,
            )

    for pattern in _TENANCY_LEGAL_PATTERNS:
        m = pattern.search(lowered)
        if m:
            return GuardrailDecision(
                action="redirect",
                reason=f"tenancy_legal:{m.group(0)}",
                reply=REDIRECT_TENANCY_LEGAL,
            )

    for pattern in _MEDICAL_PATTERNS:
        m = pattern.search(lowered)
        if m:
            return GuardrailDecision(
                action="redirect",
                reason=f"medical:{m.group(0)}",
                reply=REDIRECT_MEDICAL,
            )

    for pattern in _SAFETY_ADVICE_PATTERNS:
        m = pattern.search(lowered)
        if m:
            return GuardrailDecision(
                action="redirect",
                reason=f"safety_advice:{m.group(0)}",
                reply=REDIRECT_SAFETY_ADVICE,
            )

    return GuardrailDecision(action="allow")
