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
import time
from pathlib import Path

import litellm
from pydantic import ValidationError

from hero.graph.state import Claim, Hypothesis, SufficiencyResult, TicketState, TriageResult
from hero.interfaces.vlm import DiagnosisParseError, SufficiencyParseError, TriageParseError
from hero.verification.claims import gather_evidence_text

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
_TRIAGE_PROMPT = _load_prompt("triage")
_SUFFICIENCY_PROMPT = _load_prompt("sufficiency")

# Generic-question markers (P4-5): an "insufficient" verdict whose question
# contains any of these is rejected at parse time — it must never reach a
# tenant. The prompt bans them; this is the deterministic backstop.
_GENERIC_QUESTION_MARKERS: tuple[str, ...] = (
    "more detail",
    "more information",
    "additional detail",
    "additional information",
    "please provide",
    "please describe",
    "can you clarify",
    "could you clarify",
    "can you describe",
    "could you describe",
    "tell me more",
    "tell us more",
    "elaborate",
    "describe the issue",
    "describe the problem",
)


def parse_triage(raw: str) -> TriageResult:
    """Strictly parse a triage response (BL-4).

    TriageResult's Literal fields are the vocabulary gate — any
    out-of-vocabulary value raises TriageParseError. The TRIAGE node
    catches it and falls back to the keyword classifier (full path).
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TriageParseError(f"triage response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TriageParseError(f"triage response is not an object: {data!r:.200}")
    try:
        return TriageResult.model_validate(data)
    except ValidationError as exc:
        raise TriageParseError(f"triage response failed validation: {exc}") from exc


def parse_diagnosis(raw: str) -> list[Hypothesis]:
    """Strictly parse a diagnosis response into hypotheses.

    Raises DiagnosisParseError on any shape violation — never fabricates a
    placeholder fault (P3-1.5). Module-level so tests can exercise it
    without mocking LiteLLM.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DiagnosisParseError(f"diagnosis response is not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        data = data.get("hypotheses")
    if not isinstance(data, list) or not data:
        raise DiagnosisParseError("diagnosis response has no hypotheses list")

    hypotheses: list[Hypothesis] = []
    for item in data:
        if not isinstance(item, dict):
            raise DiagnosisParseError(f"hypothesis is not an object: {item!r:.200}")
        fault = item.get("fault")
        if not isinstance(fault, str) or not fault.strip():
            raise DiagnosisParseError("hypothesis missing non-empty 'fault'")

        raw_claims = item.get("claims")
        if not isinstance(raw_claims, list) or not raw_claims:
            raise DiagnosisParseError(f"hypothesis {fault!r} missing non-empty 'claims' list")
        claims: list[Claim] = []
        for c in raw_claims:
            text = c.get("text") if isinstance(c, dict) else c
            if not isinstance(text, str) or not text.strip():
                raise DiagnosisParseError(f"claim without text in hypothesis {fault!r}")
            claims.append(Claim(text=text))

        raw_reasoning = item.get("reasoning", [])
        if not isinstance(raw_reasoning, list):
            raise DiagnosisParseError(f"'reasoning' is not a list in hypothesis {fault!r}")
        reasoning = [str(r) for r in raw_reasoning if str(r).strip()]

        hypotheses.append(
            Hypothesis(
                fault=fault,
                claims=claims,
                reasoning=reasoning,
                # INV-4: calibrated_confidence is NEVER set here.
                # It is set only by the Calibrator after VERIFY.
            )
        )

    return hypotheses


def parse_sufficiency(raw: str) -> SufficiencyResult:
    """Strictly parse a sufficiency response (P4-5).

    The generic-question gate is part of parsing: an insufficient verdict
    whose question is missing, too short, or generic raises
    SufficiencyParseError — the RETRIEVE node fails open to DIAGNOSE.
    A generic question must never be surfaced to a tenant.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SufficiencyParseError(f"sufficiency response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SufficiencyParseError(f"sufficiency response is not an object: {data!r:.200}")
    try:
        result = SufficiencyResult.model_validate(data)
    except ValidationError as exc:
        raise SufficiencyParseError(f"sufficiency response failed validation: {exc}") from exc

    if result.sufficient:
        # A stray question alongside sufficient=true is dropped, never surfaced.
        return SufficiencyResult(sufficient=True)

    question = (result.question or "").strip()
    if len(question) < 10:
        raise SufficiencyParseError(f"insufficient verdict without a usable question: {question!r}")
    lowered = question.lower()
    if any(marker in lowered for marker in _GENERIC_QUESTION_MARKERS):
        raise SufficiencyParseError(f"generic question rejected: {question!r}")
    return SufficiencyResult(sufficient=False, question=question)


class LiteLLMVLM:
    """VLM Protocol implementation using LiteLLM for tiered model routing.

    Logs which model served each call for tracing/debugging.
    """

    def __init__(
        self,
        primary_model: str = "claude-fable-5",
        verify_model: str = "claude-sonnet-4-6",
        fallback_model: str = "gpt-4o",
        triage_model: str = "",
    ) -> None:
        self._primary = primary_model
        self._verify = verify_model
        self._fallback = fallback_model
        # Empty = triage on the verify tier (DEC-18 as amended 2026-07 after
        # the P3-4 experiment: sonnet triage matched fable on routing quality
        # at ~1/3 the latency and cost, with zero run-to-run flips). Non-empty
        # overrides explicitly; DEC-21 fail-safes are model-agnostic.
        self._triage = triage_model or verify_model
        # Accumulated usage per tier since the last drain_usage() call.
        # tier -> {"calls", "cost_usd", "prompt_tokens", "completion_tokens"}
        self._usage: dict[str, dict[str, float]] = {}

    def drain_usage(self) -> dict[str, dict[str, float]]:
        """Return accumulated per-tier usage and reset the counters.

        The eval harness calls this per ticket so cost/ticket is measured,
        not reconstructed (P3-1.5 baseline finding: cost was hard-coded 0.0).
        """
        usage = self._usage
        self._usage = {}
        return usage

    async def _call(self, model: str, prompt: str, tier: str) -> str:
        """Call LiteLLM with fallback. Logs model and tier.

        No `temperature` param: newer Anthropic models reject it
        ("`temperature` is deprecated for this model") — found live 2026-07-10.
        Model IDs are config-driven (DEC-18), so we omit it for all tiers
        rather than special-casing model names.
        """
        t0 = time.monotonic()
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
            self._log_cost(response, tier, time.monotonic() - t0)
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
            # Elapsed includes the failed primary attempt — the wall time the
            # ticket actually paid, which is what the eval reports (P4-5d).
            self._log_cost(response, tier, time.monotonic() - t0)
            return content

    def _log_cost(self, response: object, tier: str, elapsed_s: float) -> None:
        """Log and accumulate LiteLLM-computed cost + token usage per call."""
        try:
            cost = getattr(response, "_hidden_params", {}).get("response_cost")
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            logger.info(
                "[VLM-COST] tier=%s cost_usd=%s prompt_tokens=%s completion_tokens=%s",
                tier,
                cost,
                prompt_tokens,
                completion_tokens,
            )
            bucket = self._usage.setdefault(
                tier,
                {
                    "calls": 0,
                    "cost_usd": 0.0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "latency_s": 0.0,
                },
            )
            bucket["calls"] += 1
            bucket["cost_usd"] += float(cost or 0.0)
            bucket["prompt_tokens"] += int(prompt_tokens or 0)
            bucket["completion_tokens"] += int(completion_tokens or 0)
            bucket["latency_s"] += elapsed_s
        except Exception:  # never let metrics logging break a call
            logger.debug("[VLM-COST] tier=%s cost unavailable", tier)

    async def triage(self, description: str) -> TriageResult:
        """Classify trade + urgency + complexity.

        Verify-tier model by default (DEC-18 as amended); `triage_model`
        overrides. Raises TriageParseError on unparseable output; the TRIAGE
        node falls back to the keyword classifier (BL-4).
        """
        prompt = _render(_TRIAGE_PROMPT, description=description)
        tier = "primary/triage" if self._triage == self._primary else "triage"
        raw = await self._call(self._triage, prompt, tier)
        return parse_triage(raw)

    async def diagnose(self, state: TicketState) -> list[Hypothesis]:
        """Form fault hypotheses — uses PRIMARY model (reasoning-heavy).

        The prompt receives real manual excerpts (same text VERIFY entails
        against) so claims can cite them — not just doc-id/score lines,
        which produced ungroundable meta-claims in the live baseline.

        Raises DiagnosisParseError when the response does not parse into
        the expected shape — the DIAGNOSE node escalates (P3-1.5).
        """
        evidence_text = gather_evidence_text([e.model_dump() for e in state.evidence])

        prompt = _render(
            _DIAGNOSE_PROMPT,
            description=state.description,
            trade=state.trade or "unknown",
            evidence=evidence_text,
        )

        raw = await self._call(self._primary, prompt, "primary/diagnose")
        return parse_diagnosis(raw)

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

    async def assess_sufficiency(self, state: TicketState) -> SufficiencyResult:
        """Judge diagnosis-readiness — uses VERIFY model (P4-5, INV-5).

        Raises SufficiencyParseError on unparseable output or a generic
        question; the RETRIEVE node fails open (proceeds to DIAGNOSE) —
        a bad sufficiency call must never block a ticket.
        """
        evidence_text = gather_evidence_text([e.model_dump() for e in state.evidence])
        prompt = _render(
            _SUFFICIENCY_PROMPT,
            description=state.description,
            trade=state.trade or "unknown",
            evidence=evidence_text,
        )
        raw = await self._call(self._verify, prompt, "verify/sufficiency")
        return parse_sufficiency(raw)

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
