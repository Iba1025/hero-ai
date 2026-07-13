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

    # ── LiteLLM / VLM tiered routing (DEC-18) ──────────────────────────
    vlm_model_primary: str = Field(
        default="claude-fable-5",
        description="Frontier model for DIAGNOSE/TRIAGE (reasoning-heavy)",
    )
    vlm_model_verify: str = Field(
        default="claude-sonnet-4-6",
        description="Cheaper model for decompose_claims/check_entailment (high-volume)",
    )
    vlm_model_fallback: str = Field(
        default="gpt-4o",
        description="Cross-provider fallback for both tiers",
    )
    vlm_model_triage: str = Field(
        default="",
        description=(
            "Optional TRIAGE model override; empty = vlm_model_verify "
            "(DEC-18 as amended 2026-07). DEC-21 keyword fail-safes apply regardless"
        ),
    )
    vlm_model_chat: str = Field(
        default="claude-haiku-4-5-20251001",
        description=(
            "Nova conversational tier (Phase 5, DEC-23) — haiku-class by default. "
            "Tenant intake chat ONLY; diagnosis always runs the full verified "
            "pipeline on the primary tier"
        ),
    )
    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")

    # ── Auth (P4-1) ──────────────────────────────────────────────────────
    jwt_secret_key: str = Field(
        default="",
        description="HS256 signing secret. Empty = auth endpoints return 503 (fail loudly)",
    )
    jwt_expiry_seconds: int = Field(
        default=43200, description="Session cookie/token TTL — 12h covers a field workday"
    )
    auth_cookie_secure: bool = Field(
        default=False,
        description="Set the Secure flag on the session cookie (enable behind HTTPS)",
    )
    cors_origins: str = Field(
        default="http://localhost:5173",
        description="Comma-separated SPA origins allowed to send credentialed requests",
    )

    # ── Public tenant intake (P4-4) — abuse basics, no CAPTCHA at pilot ──
    public_intake_rate_per_hour: int = Field(
        default=10, description="Ticket submissions per building link per hour"
    )
    public_presign_rate_per_hour: int = Field(
        default=30, description="Photo presigns per building link per hour"
    )
    public_answer_rate_per_hour: int = Field(
        default=20, description="Clarify answers per ticket status link per hour"
    )
    public_max_photos: int = Field(default=6, description="Max photos per public ticket")
    public_max_photo_bytes: int = Field(
        default=10 * 1024 * 1024, description="Max declared photo size for a public presign"
    )

    # ── Nova conversational intake (Phase 5 STEP 2 — DEC-23/24) ─────────
    nova_max_reply_tokens: int = Field(
        default=300,
        description="HARD token cap per Nova reply (passed as max_tokens — provider-enforced)",
    )
    nova_max_messages: int = Field(
        default=30,
        description=(
            "Per-conversation message cap (history entries). Past it Nova stops "
            "calling the model and returns fixed hand-off copy"
        ),
    )
    nova_cost_ceiling_usd: float = Field(
        default=0.25,
        description=(
            "Per-ticket chat-tier cost ceiling. Breaches are LOGGED (WARNING), "
            "not blocking — the token/message caps are the hard limits"
        ),
    )

    # ── Adapter selectors (swappable interfaces — DEC-2, DEC-8, DEC-5) ──
    embedder_impl: Literal["colmodernvbert", "colqwen3", "stub"] = Field(default="stub")
    reranker_impl: Literal["bge", "cohere", "stub"] = Field(default="stub")
    calibrator_impl: Literal["platt", "isotonic", "stub"] = Field(default="platt")
    vlm_impl: Literal["litellm", "stub"] = Field(
        default="stub",
        description=(
            "VLM adapter for the API graph (BL-19): 'litellm' = tiered live routing "
            "(DEC-18), 'stub' = deterministic demo/test default. Live adapters load "
            "at startup (lifespan), never on a user request"
        ),
    )

    # ── Retrieval / verification tuning ──────────────────────────────────
    grounding_threshold: float = Field(
        default=0.8,
        description="VERIFY grounding-rate threshold for descriptive claims (BL-6/DEC-6)",
    )
    grounding_threshold_strict: float = Field(
        default=1.0,
        description="VERIFY grounding-rate threshold for part-number/model-code claims (BL-6)",
    )
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
