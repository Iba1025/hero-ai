"""VERIFY node — ground each claim against evidence (spec §8).

Per hypothesis: decompose claims → check entailment → set grounded flag.
verify_pass = (grounded / total) >= threshold.
calibrated_confidence set by Calibrator only (INV-4).
"""

from __future__ import annotations

from typing import Any

from hero.interfaces.calibrator import Calibrator
from hero.interfaces.vlm import VLM


def make_verify(vlm: VLM, calibrator: Calibrator, grounding_threshold: float) -> Any:
    """Factory that returns a verify node with injected adapters."""

    async def verify(state: dict[str, Any]) -> dict[str, Any]:
        hypotheses = state.get("hypotheses", [])
        trade = state.get("trade", "other")

        updated_hypotheses = []
        overall_pass = True

        for hyp in hypotheses:
            claims = hyp.get("claims", [])
            total = len(claims)
            grounded_count = 0

            updated_claims = []
            for claim in claims:
                claim_text = claim.get("text", "")
                # In stub: VLM.check_entailment always returns True
                is_grounded = await vlm.check_entailment(claim_text, "stub evidence")
                if is_grounded:
                    grounded_count += 1
                updated_claims.append({**claim, "grounded": is_grounded})

            grounding_rate = grounded_count / total if total > 0 else 0.0
            passes = grounding_rate >= grounding_threshold

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
