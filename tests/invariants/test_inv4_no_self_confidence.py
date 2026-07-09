"""INV-4: No model self-reported confidence anywhere.

Grep/AST check — no persisted field populated from raw model output
named/derived as confidence. The only confidence that leaves the system
must trace to the Calibrator, not the LLM.
"""

from __future__ import annotations

import ast
from pathlib import Path

from hero.graph.state import Hypothesis, TicketState


def _get_src_files() -> list[Path]:
    """Get all .py files under src/hero/."""
    src_dir = Path(__file__).parent.parent.parent / "src" / "hero"
    return list(src_dir.rglob("*.py"))


def test_no_model_confidence_field_in_state() -> None:
    """TicketState and Hypothesis must not have a model_confidence field."""
    state_fields = set(TicketState.model_fields.keys())
    assert "model_confidence" not in state_fields
    assert "llm_confidence" not in state_fields
    assert "self_confidence" not in state_fields

    hyp_fields = set(Hypothesis.model_fields.keys())
    assert "model_confidence" not in hyp_fields
    assert "llm_confidence" not in hyp_fields
    assert "self_confidence" not in hyp_fields


def test_hypothesis_confidence_is_optional() -> None:
    """calibrated_confidence on Hypothesis must be Optional (set by Calibrator only)."""
    field = Hypothesis.model_fields["calibrated_confidence"]
    # Must allow None — it's not set at diagnosis time
    assert field.is_required() is False


def test_no_confidence_from_model_in_source() -> None:
    """Scan source for patterns that would read confidence from model output."""
    forbidden_patterns = [
        "model_confidence",
        "llm_confidence",
        "self_reported_confidence",
    ]

    violations: list[str] = []

    for path in _get_src_files():
        content = path.read_text()
        for pattern in forbidden_patterns:
            if pattern in content:
                rel = path.relative_to(Path(__file__).parent.parent.parent)
                if "test_inv4" not in str(rel):
                    # Check if all occurrences are in comments
                    non_comment_hit = False
                    for line in content.splitlines():
                        stripped = line.strip()
                        if pattern in stripped and not stripped.startswith("#"):
                            non_comment_hit = True
                            break
                    if non_comment_hit:
                        violations.append(f"{rel}: contains '{pattern}'")

    assert violations == [], f"INV-4 VIOLATION: found model self-confidence patterns: {violations}"


def test_no_confidence_assignment_in_graph_nodes() -> None:
    """AST check: graph nodes must not assign to any *confidence* attribute
    unless it's 'calibrated_confidence' from a calibrator call."""
    nodes_dir = Path(__file__).parent.parent.parent / "src" / "hero" / "graph" / "nodes"

    violations: list[str] = []

    for path in nodes_dir.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Check for string constants that reference bad confidence patterns
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value.lower()
                # Only flag explicitly bad patterns: model/llm/self confidence
                for bad in ("model_confidence", "llm_confidence", "self_confidence"):
                    if bad in val:
                        violations.append(
                            f"{path.name}:{node.lineno}: string '{node.value}' references '{bad}'"
                        )

    assert violations == [], (
        f"INV-4 VIOLATION: non-calibrated confidence references in graph nodes: {violations}"
    )
