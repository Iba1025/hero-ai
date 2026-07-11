"""Claim classification + evidence gathering for claim-level VERIFY (BL-6, DEC-6).

Deterministic, data-as-code — no LLM calls here (classification must be
auditable and free, like safety/hazards.py). The classifier decides which
grounding threshold applies per claim (spec §8):

- "part_number": claim cites a part number / model code — threshold 1.0
  (GROUNDING_THRESHOLD_STRICT). A wrong part number is an ordering error;
  partial grounding is not acceptable.
- "descriptive": everything else — threshold 0.8 (GROUNDING_THRESHOLD).
"""

from __future__ import annotations

import re
from typing import Any, Literal

ClaimType = Literal["part_number", "descriptive"]

# Part-number / model-code shapes: an uppercase letter block joined to at
# least one digit block, optionally followed by more alnum blocks.
# Matches: PT-100-SS, PL-2000, FC-200-BR, XR16, M8-1.25
# Does NOT match: P-trap (lowercase tail), HVAC (no digits), "page 12" (no
# letter block fused to the digits).
_PART_CODE = re.compile(
    r"\b[A-Z]{1,6}-?\d{1,6}(?:[-.][A-Z0-9]{1,6})*\b",
)


def classify_claim(text: str) -> ClaimType:
    """Classify a claim as part_number or descriptive (deterministic)."""
    if _PART_CODE.search(text):
        return "part_number"
    return "descriptive"


def gather_evidence_text(
    evidence: list[dict[str, Any]],
    max_chunks: int = 5,
    max_chars_per_chunk: int = 2000,
) -> str:
    """Assemble entailment input from retrieved evidence chunks (spec §8).

    Uses the page text carried on each chunk (Qdrant payload → EvidenceChunk.text).
    Chunks without text contribute their citation line only — never invented text.
    """
    lines: list[str] = []
    for chunk in evidence[:max_chunks]:
        doc_id = chunk.get("doc_id", "?")
        page = chunk.get("page", "?")
        header = f"[{doc_id} p{page}]"
        text = chunk.get("text")
        if text:
            lines.append(f"{header} {str(text)[:max_chars_per_chunk]}")
        else:
            lines.append(header)
    return "\n\n".join(lines) if lines else "No evidence retrieved."
