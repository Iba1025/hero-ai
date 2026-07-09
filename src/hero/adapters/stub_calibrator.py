"""Stub Calibrator — deterministic fake for skeleton testing."""

from __future__ import annotations


class StubCalibrator:
    """Identity calibrator: returns raw score as-is. ECE fixed at 0.0."""

    def calibrate(self, raw_grounding_score: float, trade: str) -> float:
        return raw_grounding_score

    def fit(self, outcomes: list[tuple[float, bool]]) -> None:
        pass

    def ece(self) -> float:
        return 0.0
