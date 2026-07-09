"""Hero.AI configuration — pydantic-settings, all env vars typed here.

No os.environ reads elsewhere in the codebase (spec §3).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Allowed Canadian regions (INV-2)
# ---------------------------------------------------------------------------
_CANADIAN_REGION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ca-central-\d+"),
    re.compile(r"ca-west-\d+"),
    re.compile(r"\.ca\."),  # e.g. Cloudflare R2 ca jurisdiction URLs
]


def _looks_canadian(value: str) -> bool:
    """Return True if *value* contains a recognisable Canadian region token."""
    lower = value.lower()
    return any(p.search(lower) for p in _CANADIAN_REGION_PATTERNS)


class Settings(BaseSettings):
    """Typed config — single source of truth for all env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Postgres ──────────────────────────────────────────────────────────
    database_url: str = Field(
        ...,
        description="Postgres connection string (ca-central instance)",
    )

    # ── Qdrant (DEC-3) ───────────────────────────────────────────────────
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str = Field(default="")

    # ── R2 / S3 object storage (INV-3: presigning only) ──────────────────
    r2_endpoint: str = Field(default="")
    r2_bucket: str = Field(default="hero-media")
    r2_access_key_id: str = Field(default="")
    r2_secret_access_key: str = Field(default="")
    r2_region: str = Field(
        default="auto",
        description="Bucket region — must be 'auto' (R2 ca) or a Canadian region (INV-2)",
    )

    # ── Langfuse (self-hosted, ca-central — INV-2) ───────────────────────
    langfuse_host: str = Field(default="")
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")

    # ── LiteLLM / provider keys ──────────────────────────────────────────
    litellm_primary_model: str = Field(default="claude-sonnet-4-20250514")
    litellm_fallback_model: str = Field(default="gpt-4o")
    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")

    # ── Adapter selectors (swappable interfaces — DEC-2, DEC-8, DEC-5) ──
    embedder_impl: Literal["colmodernvbert", "colqwen3", "stub"] = Field(default="stub")
    reranker_impl: Literal["bge", "cohere", "stub"] = Field(default="stub")
    calibrator_impl: Literal["platt", "isotonic", "stub"] = Field(default="stub")

    # ── Retrieval tuning ─────────────────────────────────────────────────
    grounding_threshold: float = Field(default=0.8)
    max_clarify_rounds: int = Field(default=3)
    max_corrective_rounds: int = Field(default=2)
    corrective_timeout_s: float = Field(default=10.0)

    # ── Dev-only flags (never set in CI/prod) ────────────────────────────
    hero_eval_memory_checkpointer: bool = Field(
        default=False,
        description=(
            "Use MemorySaver instead of PostgresSaver. "
            "Local dev convenience ONLY — CI must never set this. "
            "INV-6 requires persistent checkpoints in all real runs."
        ),
    )


def region_guard(settings: Settings) -> None:
    """Fail loudly if any detectable store resolves outside Canada (INV-2).

    Called at app startup. Raises ``RuntimeError`` on violation.
    """
    checks: list[tuple[str, str]] = [
        ("DATABASE_URL", settings.database_url),
        ("QDRANT_URL", settings.qdrant_url),
        ("LANGFUSE_HOST", settings.langfuse_host),
    ]

    for name, value in checks:
        if not value:
            continue  # unconfigured — skip (dev/test)
        # Localhost / loopback is always fine (local dev)
        if any(tok in value for tok in ("localhost", "127.0.0.1", "::1")):
            continue
        # R2 "auto" region is fine (maps to ca jurisdiction via Cloudflare config)
        if name == "R2_ENDPOINT" and settings.r2_region == "auto":
            continue
        # Detectable non-Canadian region → hard fail
        if _has_non_canadian_region(value):
            raise RuntimeError(
                f"INV-2 VIOLATION: {name} appears to reference a non-Canadian region "
                f"({value!r}). All stores must sit in a Canadian region. "
                f"See HERO_AI_PRD.md §2 INV-2."
            )


def _has_non_canadian_region(value: str) -> bool:
    """Return True if value contains a recognisable non-Canadian cloud region."""
    # Match common AWS/GCP/Azure region patterns
    region_pattern = re.compile(
        r"(us|eu|ap|sa|af|me|il)-[a-z]+-\d+"  # AWS-style
        r"|us-central\d+"  # GCP-style
        r"|europe-west\d+"
        r"|asia-east\d+"
    )
    match = region_pattern.search(value.lower())
    if match:
        # But it's fine if it's actually Canadian
        return not _looks_canadian(value)
    return False


def get_settings() -> Settings:
    """Construct and return validated settings from environment."""
    return Settings()
