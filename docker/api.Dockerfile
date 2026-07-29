# syntax=docker/dockerfile:1
# Hero.AI API image — LEAN MODE (Phase 6, DEC-27 as amended by DEC-29).
#
# No torch, no model weights: embed/rerank are Bedrock-hosted in
# ca-central-1 (DEC-29). `uv sync` here installs BASE dependencies only —
# the self-hosted torch stack is the `selfhosted` extra (pyproject), which
# this image deliberately does NOT install. Reinstating it (DEC-29 reversion
# trigger) = add `--extra selfhosted` + restore the hf_cache volume from
# git history.
#
# Cold start is therefore: interpreter + app import + blocking orphan
# recovery (spec §3) — no weight download, no weight load.

FROM python:3.12-slim AS builder

# uv pinned to the version the lockfile was generated with (uv 0.11.x).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer first — cached until pyproject/uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# App layer: source + migrations (prompts ship inside src/hero/prompts).
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim

# Non-root runtime user.
RUN useradd --create-home --uid 1000 hero

WORKDIR /app
COPY --from=builder --chown=hero:hero /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER hero
EXPOSE 8000

# Liveness probe against the shallow /health route. start_period covers
# blocking orphan recovery (spec §3) — no model download (DEC-29).
HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=120s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

CMD ["uvicorn", "hero.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
