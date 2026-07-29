"""BL-81 — hazard red-team recall report (INV-15, INV-20 shape).

Prints recall per hazard category over the adversarial corpus, plus the
benign false-positive count. Exit 1 if any must-catch phrase is missed —
a hazard scanner with unmeasured recall is exactly the INV-20 failure shape.

Usage: uv run python evals/run_hazard_recall.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.hazard_redteam_cases import BENIGN, MUST_CATCH
from hero.safety.hazards import scan_hazards


def main() -> int:
    print(f"\n{'=' * 70}")
    print("Hazard red-team recall (BL-81) — deterministic scan, INV-15 floor")
    print(f"{'=' * 70}\n")

    misses: list[tuple[str, str]] = []
    print(f"{'category':<18} {'caught':>7} {'total':>6} {'recall':>8}")
    for category, phrases in MUST_CATCH.items():
        caught = [p for p in phrases if scan_hazards(p)]
        for p in phrases:
            if p not in caught:
                misses.append((category, p))
        print(
            f"{category:<18} {len(caught):>7} {len(phrases):>6} {len(caught) / len(phrases):>7.0%}"
        )

    false_positives = [(p, scan_hazards(p)) for p in BENIGN if scan_hazards(p)]
    total = sum(len(v) for v in MUST_CATCH.values())
    print(f"\nmust-catch: {total - len(misses)}/{total}")
    print(f"benign false positives: {len(false_positives)}/{len(BENIGN)}")

    for category, phrase in misses:
        print(f"  MISS [{category}]: {phrase!r}")
    for phrase, hits in false_positives:
        print(f"  FP: {phrase!r} -> {[(h.category, h.matched) for h in hits]}")

    if misses:
        print("\nFAIL — recall gap: grow the patterns in safety/hazards.py (BL-81)")
        return 1
    print("\nPASS — 100% must-catch recall per category")
    return 0


if __name__ == "__main__":
    sys.exit(main())
