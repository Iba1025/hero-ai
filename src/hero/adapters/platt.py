"""Calibrator adapters — Platt scaling (default) + isotonic regression (BL-2, DEC-5).

DEC-5: Platt (logistic sigmoid) is the default because it is robust with few
labels. Isotonic regression is more flexible but overfits small label sets, so
``IsotonicCalibrator.fit`` is a no-op below ``MIN_LABELS_ISOTONIC`` (1000) —
the adapter stays in identity mode until enough ContractorStatement labels
accumulate.

INV-4: these calibrators are the ONLY source of ``calibrated_confidence``.
Input is the mechanical per-claim grounding rate from VERIFY — never a model
self-reported score.

The ``trade`` argument is accepted per the Protocol but currently ignored:
per-trade calibration requires per-trade label volume we don't have yet.
Revisit once the flywheel (BL-0) accumulates labels per trade.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# DEC-5: isotonic regression only activates at this label count.
MIN_LABELS_ISOTONIC = 1000

_ECE_BINS = 10


def expected_calibration_error(
    probs: list[float], labels: list[bool], n_bins: int = _ECE_BINS
) -> float:
    """Standard binned ECE: sum over bins of |accuracy - confidence| * bin_weight."""
    if not probs:
        return 0.0
    n = len(probs)
    total = 0.0
    for b in range(n_bins):
        lo = b / n_bins
        hi = (b + 1) / n_bins
        # Last bin is right-inclusive so prob=1.0 lands somewhere.
        in_bin = [
            (p, y)
            for p, y in zip(probs, labels, strict=True)
            if (lo <= p < hi) or (b == n_bins - 1 and p == hi)
        ]
        if not in_bin:
            continue
        avg_conf = sum(p for p, _ in in_bin) / len(in_bin)
        accuracy = sum(1 for _, y in in_bin if y) / len(in_bin)
        total += abs(accuracy - avg_conf) * (len(in_bin) / n)
    return total


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


class PlattCalibrator:
    """Platt scaling: logistic regression on the raw grounding rate.

    Identity (clamped) until ``fit`` succeeds — safe drop-in for StubCalibrator
    before any labels exist.
    """

    def __init__(self) -> None:
        self._model: object | None = None
        self._ece: float = 0.0

    def calibrate(self, raw_grounding_score: float, trade: str) -> float:
        raw = _clamp(raw_grounding_score)
        if self._model is None:
            return raw
        prob = self._model.predict_proba([[raw]])[0][1]  # type: ignore[attr-defined]
        return float(prob)

    def fit(self, outcomes: list[tuple[float, bool]]) -> None:
        """Fit on (predicted_score, actual_correct) pairs.

        Requires at least 2 samples and both classes present; otherwise stays
        in identity mode (logged, not raised — callers fit opportunistically).
        """
        labels = [y for _, y in outcomes]
        if len(outcomes) < 2 or len(set(labels)) < 2:
            logger.warning(
                "[PlattCalibrator] fit skipped: need >=2 samples with both classes "
                "(got n=%d, classes=%d) — staying in identity mode",
                len(outcomes),
                len(set(labels)),
            )
            return

        from sklearn.linear_model import LogisticRegression

        model = LogisticRegression()
        model.fit([[_clamp(s)] for s, _ in outcomes], labels)
        self._model = model

        probs = [self.calibrate(s, "") for s, _ in outcomes]
        self._ece = expected_calibration_error(probs, labels)
        logger.info("[PlattCalibrator] fitted on %d outcomes, ECE=%.4f", len(outcomes), self._ece)

    def ece(self) -> float:
        return self._ece


class IsotonicCalibrator:
    """Isotonic regression — gated behind label_count >= 1000 (DEC-5).

    Below the gate, ``fit`` is a no-op and ``calibrate`` is identity. This
    keeps the adapter selectable via CALIBRATOR_IMPL=isotonic without risking
    an overfit monotone step function on a small label set.
    """

    def __init__(self) -> None:
        self._model: object | None = None
        self._ece: float = 0.0

    def calibrate(self, raw_grounding_score: float, trade: str) -> float:
        raw = _clamp(raw_grounding_score)
        if self._model is None:
            return raw
        prob = self._model.predict([raw])[0]  # type: ignore[attr-defined]
        return float(prob)

    def fit(self, outcomes: list[tuple[float, bool]]) -> None:
        if len(outcomes) < MIN_LABELS_ISOTONIC:
            logger.warning(
                "[IsotonicCalibrator] fit skipped: %d labels < %d gate (DEC-5) "
                "— staying in identity mode. Use PlattCalibrator until then.",
                len(outcomes),
                MIN_LABELS_ISOTONIC,
            )
            return

        from sklearn.isotonic import IsotonicRegression

        labels = [y for _, y in outcomes]
        model = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        model.fit([_clamp(s) for s, _ in outcomes], [1.0 if y else 0.0 for y in labels])
        self._model = model

        probs = [self.calibrate(s, "") for s, _ in outcomes]
        self._ece = expected_calibration_error(probs, labels)
        logger.info(
            "[IsotonicCalibrator] fitted on %d outcomes, ECE=%.4f", len(outcomes), self._ece
        )

    def ece(self) -> float:
        return self._ece
