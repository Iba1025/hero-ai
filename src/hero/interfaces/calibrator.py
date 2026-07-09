"""Calibrator Protocol — spec §6 (DEC-5: platt default; isotonic >= 1000 labels)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Calibrator(Protocol):
    def calibrate(self, raw_grounding_score: float, trade: str) -> float:
        """Map raw grounding rate to calibrated confidence."""
        ...

    def fit(self, outcomes: list[tuple[float, bool]]) -> None:
        """Fit calibrator on (predicted_score, actual_correct) pairs."""
        ...

    def ece(self) -> float:
        """Expected calibration error — tracked metric."""
        ...
