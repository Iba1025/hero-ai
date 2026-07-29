"""INV-15 / BL-81 — hazard red-team recall suite.

The corpus (evals/hazard_redteam_cases.py) is the ground truth; the pattern
list in safety/hazards.py is an output of this suite. Recall on MUST_CATCH is
asserted at 100% per category — a miss here is a life-safety gap, not a flaky
test. BENIGN is the precision floor: ordinary maintenance reports must flow.

Also asserts the compatibility superset (every legacy HAZARD_KEYWORDS literal
still fires) and that both consumers — the Nova guardrail and the pipeline
safety gate — escalate on every corpus phrase (INV-15 monotonicity: layers
may add escalations; no wiring change may lose one).
"""

from __future__ import annotations

import pytest
from evals.hazard_redteam_cases import BENIGN, MUST_CATCH

from hero.nova.guardrails import check_message
from hero.safety.gate import safety_check
from hero.safety.hazards import HAZARD_CATEGORIES, HAZARD_KEYWORDS, scan_hazards

_ALL_CASES = [(cat, phrase) for cat, phrases in MUST_CATCH.items() for phrase in phrases]


@pytest.mark.parametrize(("category", "phrase"), _ALL_CASES)
def test_must_catch_phrase_is_detected(category: str, phrase: str) -> None:
    """Escalation is category-agnostic: a hit in ANY category counts as caught."""
    assert scan_hazards(phrase), f"MISSED [{category}]: {phrase!r} — recall gap (BL-81)"


def test_recall_is_total_per_category() -> None:
    """The per-category recall numbers — the INV-20-shaped instrumentation.

    Same check as above in aggregate; the failure message is the recall
    report, so a red run shows exactly which category degraded and by how
    much. evals/run_hazard_recall.py prints the same table on demand.
    """
    report = {}
    for category, phrases in MUST_CATCH.items():
        caught = sum(1 for p in phrases if scan_hazards(p))
        report[category] = (caught, len(phrases))
    assert all(c == n for c, n in report.values()), f"recall by category: {report}"


@pytest.mark.parametrize("phrase", BENIGN)
def test_benign_report_does_not_escalate(phrase: str) -> None:
    hits = scan_hazards(phrase)
    assert not hits, f"FALSE POSITIVE: {phrase!r} -> {hits}"


@pytest.mark.parametrize("keyword", HAZARD_KEYWORDS)
def test_scan_is_superset_of_legacy_keywords(keyword: str) -> None:
    """BL-81 may only widen detection — every pre-BL-81 literal still fires."""
    assert scan_hazards(keyword), f"legacy keyword no longer detected: {keyword!r}"


def test_every_category_has_corpus_coverage() -> None:
    """A detector category nobody red-teams is unmeasured recall (INV-20 shape)."""
    assert set(MUST_CATCH) == set(HAZARD_CATEGORIES)
    assert all(len(v) >= 5 for v in MUST_CATCH.values()), {k: len(v) for k, v in MUST_CATCH.items()}


# ── Consumers: both escalation paths honor every corpus phrase ──────────────


@pytest.mark.parametrize(("category", "phrase"), _ALL_CASES)
def test_nova_guardrail_escalates(category: str, phrase: str) -> None:
    decision = check_message(phrase)
    assert decision.action == "escalate", (category, phrase, decision)
    assert decision.reply is None  # never generated copy on a hazard


@pytest.mark.parametrize(("category", "phrase"), _ALL_CASES)
def test_safety_gate_escalates(category: str, phrase: str) -> None:
    decision = safety_check(trade="hvac", verify_pass=True, description=phrase, hypotheses=[])
    assert decision.escalate, (category, phrase)
    assert decision.reason == "hazard_signal"
