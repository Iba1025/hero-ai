"""LiteLLM VLM adapter — real VLM Protocol implementation (DEC-18).

Tiered routing:
- Primary (claude-fable-5): DIAGNOSE, TRIAGE — reasoning-heavy calls.
- Verify (claude-sonnet-4-6): decompose_claims, check_entailment — high-volume.
- Fallback (gpt-4o): cross-provider failover for both tiers via LiteLLM.

All model IDs are config-driven, never hard-coded (DEC-18).
Prompts loaded from src/hero/prompts/*.md at import time.
INV-4: nothing from model output ever populates a confidence field.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import litellm

from hero.graph.state import Claim, Hypothesis, TicketState

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text()


def _render(template: str, **values: str) -> str:
    """Substitute {key} tokens without str.format().

    Prompt files legitimately contain literal JSON braces (output examples);
    str.format() raises KeyError on them. Found live 2026-07-10 on the first
    real diagnose() call — stub runs never render prompts.
    """
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


_DIAGNOSE_PROMPT = _load_prompt("diagnose")
_DECOMPOSE_PROMPT = _load_prompt("decompose_claims")
_ENTAILMENT_PROMPT = _load_prompt("check_entailment")


class LiteLLMVLM:
    """VLM Protocol implementation using LiteLLM for tiered model routing.

    Logs which model served each call for tracing/debugging.
    """

    def __init__(
        self,
        primary_model: str = "claude-fable-5",
        verify_model: str = "claude-sonnet-4-6",
        fallback_model: str = "gpt-4o",
    ) -> None:
        self._primary = primary_model
        self._verify = verify_model
        self._fallback = fallback_model

    async def _call(self, model: str, prompt: str, tier: str) -> str:
        """Call LiteLLM with fallback. Logs model and tier.

        No `temperature` param: newer Anthropic models reject it
        ("`temperature` is deprecated for this model") — found live 2026-07-10.
        Model IDs are config-driven (DEC-18), so we omit it for all tiers
        rather than special-casing model names.
        """
        try:
            logger.info("[VLM] tier=%s model=%s", tier, model)
            response = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                fallbacks=[self._fallback],
            )
            content: str = response.choices[0].message.content or ""
            logger.info("[VLM] tier=%s model=%s served_by=%s", tier, model, response.model)
            self._log_cost(response, tier)
            return content
        except Exception:
            logger.warning(
                "[VLM] tier=%s model=%s failed, trying fallback=%s",
                tier,
                model,
                self._fallback,
            )
            response = await litellm.acompletion(
                model=self._fallback,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            logger.info("[VLM] tier=%s served_by=%s (fallback)", tier, self._fallback)
            self._log_cost(response, tier)
            return content

    @staticmethod
    def _log_cost(response: object, tier: str) -> None:
        """Log LiteLLM-computed cost + token usage per call (baseline metrics)."""
        try:
            cost = getattr(response, "_hidden_params", {}).get("response_cost")
            usage = getattr(response, "usage", None)
            logger.info(
                "[VLM-COST] tier=%s cost_usd=%s prompt_tokens=%s completion_tokens=%s",
                tier,
                cost,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )
        except Exception:  # never let metrics logging break a call
            logger.debug("[VLM-COST] tier=%s cost unavailable", tier)

    async def diagnose(self, state: TicketState) -> list[Hypothesis]:
        """Form fault hypotheses — uses PRIMARY model (reasoning-heavy)."""
        evidence_text = "\n".join(
            f"[{e.doc_id} p{e.page}] (score={e.score:.2f})" for e in state.evidence
        )

        prompt = _render(
            _DIAGNOSE_PROMPT,
            description=state.description,
            trade=state.trade or "unknown",
            evidence=evidence_text or "No evidence available",
        )

        raw = await self._call(self._primary, prompt, "primary/diagnose")

        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "hypotheses" in data:
                data = data["hypotheses"]
            if not isinstance(data, list):
                data = [data]
        except json.JSONDecodeError:
            data = [{"fault": raw.strip(), "claims": [{"text": raw.strip()}]}]

        hypotheses: list[Hypothesis] = []
        for item in data:
            claims = [
                Claim(text=c["text"] if isinstance(c, dict) else str(c))
                for c in item.get("claims", [{"text": item.get("fault", "")}])
            ]
            hypotheses.append(
                Hypothesis(
                    fault=item.get("fault", "Unknown fault"),
                    claims=claims,
                    # INV-4: calibrated_confidence is NEVER set here.
                    # It is set only by the Calibrator after VERIFY.
                )
            )

        return hypotheses

    async def decompose_claims(self, hypothesis_text: str) -> list[str]:
        """Break hypothesis into verifiable claims — uses VERIFY model (cheaper)."""
        prompt = _render(_DECOMPOSE_PROMPT, hypothesis_text=hypothesis_text)
        raw = await self._call(self._verify, prompt, "verify/decompose")

        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "claims" in data:
                data = data["claims"]
            if isinstance(data, list):
                return [str(c) for c in data]
        except json.JSONDecodeError:
            pass

        return [hypothesis_text]

    async def check_entailment(self, claim: str, evidence_text: str) -> bool:
        """Check if evidence entails claim — uses VERIFY model (cheaper)."""
        prompt = _render(_ENTAILMENT_PROMPT, claim=claim, evidence_text=evidence_text)
        raw = await self._call(self._verify, prompt, "verify/entailment")

        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return bool(data.get("result", data.get("entailment", False)))
            return bool(data)
        except (json.JSONDecodeError, TypeError):
            return "true" in raw.lower()
