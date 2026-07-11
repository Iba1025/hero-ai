"""VERIFY node — claim-level grounding against real evidence (spec §8, BL-6/DEC-6).

Per hypothesis: for each claim → classify (part_number | descriptive) →
check_entailment(claim, top evidence text) → grounded flag.

Per-type thresholds (claim classifier decides, spec §8):
- part_number claims: grounding rate must be >= GROUNDING_THRESHOLD_STRICT (1.0)
- descriptive claims: grounding rate must be >= GROUNDING_THRESHOLD (0.8)

verify_pass = every hypothesis satisfies BOTH per-type thresholds.
calibrated_confidence set by Calibrator only (INV-4).
Entailment calls go through VLM.check_entailment — the VERIFY model tier (DEC-18).
"""

from __future__ import annotations

from typing import Any

from hero.interfaces.calibrator import Calibrator
from hero.interfaces.vlm import VLM
from hero.verification.claims import classify_claim, gather_evidence_text


def _strip_text(chunk: dict[str, Any]) -> dict[str, Any]:
    """Evidence attached to claims carries citations, not page text (DDL §5)."""
    return {k: v for k, v in chunk.items() if k != "text"}


def make_verify(
    vlm: VLM,
    calibrator: Calibrator,
    grounding_threshold: float,
    grounding_threshold_strict: float = 1.0,
) -> Any:
    """Factory that returns a verify node with injected adapters."""

    async def verify(state: dict[str, Any]) -> dict[str, Any]:
        hypotheses = state.get("hypotheses", [])
        trade = state.get("trade", "other")
        evidence: list[dict[str, Any]] = state.get("evidence", [])

        # Real evidence text from retrieval (EvidenceChunk.text — BL-6).
        evidence_text = gather_evidence_text(evidence)
        claim_evidence = [_strip_text(c) for c in evidence[:5]]

        updated_hypotheses = []
        overall_pass = True

        for hyp in hypotheses:
            claims = hyp.get("claims", [])
            counts: dict[str, list[int]] = {}  # claim_type -> [grounded, total]

            updated_claims = []
            for claim in claims:
                claim_text = claim.get("text", "")
                claim_type = classify_claim(claim_text)
                is_grounded = await vlm.check_entailment(claim_text, evidence_text)

                grounded_n, total_n = counts.get(claim_type, [0, 0])
                counts[claim_type] = [grounded_n + int(is_grounded), total_n + 1]

                updated_claims.append(
                    {
                        **claim,
                        "claim_type": claim_type,
                        "grounded": is_grounded,
                        "supporting_evidence": claim_evidence if is_grounded else [],
                    }
                )

            total = sum(t for _, t in counts.values())
            grounded_count = sum(g for g, _ in counts.values())
            grounding_rate = grounded_count / total if total > 0 else 0.0

            # Per-type thresholds (spec §8): every type present must clear its bar.
            thresholds = {
                "part_number": grounding_threshold_strict,
                "descriptive": grounding_threshold,
            }
            passes = total > 0 and all(
                (grounded_n / total_n) >= thresholds[claim_type]
                for claim_type, (grounded_n, total_n) in counts.items()
            )

            if not passes:
                overall_pass = False

            # Calibrated confidence from Calibrator only (INV-4)
            calibrated = calibrator.calibrate(grounding_rate, trade)

            updated_hypotheses.append(
                {
                    **hyp,
                    "claims": updated_claims,
                    "calibrated_confidence": calibrated,
                }
            )

        return {
            "hypotheses": updated_hypotheses,
            "verify_pass": overall_pass,
        }

    return verify
