"""INV-12 — exactly one guarded resume function per graph (founder ruling, 2026-07-29).

The invariant counts resume *functions*, not HTTP endpoints: many endpoints may
delegate to the one guard, but only one place per graph may invoke it with a
``Command(resume=...)``. Today that is ``hero.api.resume.resume_with_answer``
for the ticket graph. When the job graph lands (BL-75), its ``_JobResumeGuard``
call site is added to the allowlist below — a third unlisted site is an INV-12
violation and must stop work, not be allowlisted casually.

Static AST scan so the check needs no database and cannot be fooled by
comments or docstrings.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "hero"

# path (relative to src/hero) -> exact number of Command(resume=...) call sites
_ALLOWED_RESUME_CALL_SITES: dict[str, int] = {
    "api/resume.py": 1,
}


def _resume_command_calls(tree: ast.AST) -> int:
    """Count Command(...) calls carrying a `resume` keyword argument."""
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else None)
        )
        if name == "Command" and any(kw.arg == "resume" for kw in node.keywords):
            count += 1
    return count


def test_exactly_one_guarded_resume_call_site_per_graph() -> None:
    found: dict[str, int] = {}
    for py in sorted(SRC_ROOT.rglob("*.py")):
        rel = py.relative_to(SRC_ROOT).as_posix()
        n = _resume_command_calls(ast.parse(py.read_text(), filename=rel))
        if n:
            found[rel] = n

    assert found == _ALLOWED_RESUME_CALL_SITES, (
        "INV-12 violation: Command(resume=...) call sites in src/hero do not match "
        f"the allowlist. Found {found}, allowed {_ALLOWED_RESUME_CALL_SITES}. "
        "A graph may have exactly ONE guarded resume function; if you are adding "
        "the job graph, add its single _JobResumeGuard site here in the same PR. "
        "Anything else: stop and flag (WORK_ORDER_v8.2.md §6)."
    )
