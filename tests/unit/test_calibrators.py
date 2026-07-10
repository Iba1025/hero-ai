"""Behavior tests for Platt/isotonic calibrators (BL-2, DEC-5).

Contract tests live in test_adapter_contracts.py. These test the behavior
that distinguishes the real adapters from the stub: fitting actually changes
the mapping, ECE is computed, and the isotonic DEC-5 gate holds.

sklearn only — no model downloads, runs in CI.
"""

from __future__ import annotations

from hero.adapters.platt import (
    MIN_LABELS_ISOTONIC,
    IsotonicCalibrator,
    PlattCalibrator,
    expected_calibration_error,
)


def _overconfident_outcomes(n: int = 200) -> list[tuple[float, bool]]:
    """Synthetic overconfident predictor: score 0.9 but only ~50% correct."""
    out: list[tuple[float, bool]] = []
    for i in range(n):
        out.append((0.9, i % 2 == 0))  # high score, coin-flip accuracy
        out.append((0.2, i % 10 == 0))  # low score, ~10% accuracy
    return out


# ---------------------------------------------------------------------------
# ECE helper
# ---------------------------------------------------------------------------
def test_ece_perfect_calibration_is_zero() -> None:
    # Predictions exactly matching outcomes → ECE 0
    probs = [1.0, 1.0, 0.0, 0.0]
    labels = [True, True, False, False]
    assert expected_calibration_error(probs, labels) == 0.0


def test_ece_overconfident_is_high() -> None:
    # Always predicts 0.95, only 50% correct → ECE ≈ 0.45
    probs = [0.95] * 10
    labels = [i % 2 == 0 for i in range(10)]
    ece = expected_calibration_error(probs, labels)
    assert abs(ece - 0.45) < 0.01


def test_ece_empty_is_zero() -> None:
    assert expected_calibration_error([], []) == 0.0


# ---------------------------------------------------------------------------
# PlattCalibrator
# ---------------------------------------------------------------------------
def test_platt_identity_before_fit() -> None:
    cal = PlattCalibrator()
    assert cal.calibrate(0.7, "plumbing") == 0.7
    assert cal.calibrate(1.5, "plumbing") == 1.0  # clamped
    assert cal.ece() == 0.0


def test_platt_fit_changes_mapping() -> None:
    cal = PlattCalibrator()
    cal.fit(_overconfident_outcomes())
    # Overconfident 0.9 raw score must be pulled DOWN toward observed ~50%
    calibrated = cal.calibrate(0.9, "plumbing")
    assert calibrated < 0.9
    assert 0.0 <= calibrated <= 1.0


def test_platt_fit_reduces_ece_vs_identity() -> None:
    outcomes = _overconfident_outcomes()
    raw_probs = [s for s, _ in outcomes]
    labels = [y for _, y in outcomes]
    identity_ece = expected_calibration_error(raw_probs, labels)

    cal = PlattCalibrator()
    cal.fit(outcomes)
    assert cal.ece() < identity_ece


def test_platt_fit_single_class_stays_identity() -> None:
    cal = PlattCalibrator()
    cal.fit([(0.9, True), (0.8, True)])  # one class only — cannot fit
    assert cal.calibrate(0.9, "hvac") == 0.9


def test_platt_fit_empty_stays_identity() -> None:
    cal = PlattCalibrator()
    cal.fit([])
    assert cal.calibrate(0.5, "hvac") == 0.5


def test_platt_monotonic() -> None:
    """Platt scaling is a sigmoid — must preserve score ordering."""
    cal = PlattCalibrator()
    cal.fit(_overconfident_outcomes())
    scores = [0.0, 0.25, 0.5, 0.75, 1.0]
    calibrated = [cal.calibrate(s, "plumbing") for s in scores]
    assert calibrated == sorted(calibrated)


# ---------------------------------------------------------------------------
# IsotonicCalibrator — DEC-5 gate
# ---------------------------------------------------------------------------
def test_isotonic_gate_below_threshold_stays_identity() -> None:
    cal = IsotonicCalibrator()
    outcomes = _overconfident_outcomes(100)  # 200 pairs → 400 < 1000
    assert len(outcomes) < MIN_LABELS_ISOTONIC
    cal.fit(outcomes)
    assert cal.calibrate(0.9, "plumbing") == 0.9  # gate held: identity
    assert cal.ece() == 0.0


def test_isotonic_fits_at_or_above_threshold() -> None:
    cal = IsotonicCalibrator()
    outcomes = _overconfident_outcomes(300)  # 600 pairs... need >= 1000
    outcomes += _overconfident_outcomes(200)
    assert len(outcomes) >= MIN_LABELS_ISOTONIC
    cal.fit(outcomes)
    calibrated = cal.calibrate(0.9, "plumbing")
    assert calibrated != 0.9  # mapping actually changed
    assert 0.0 <= calibrated <= 1.0


def test_isotonic_gate_constant_is_1000() -> None:
    """DEC-5 pins the gate at 1000 labels — changing it is a decision-log change."""
    assert MIN_LABELS_ISOTONIC == 1000
