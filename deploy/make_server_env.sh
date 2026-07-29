#!/usr/bin/env bash
# Build /opt/hero/.env.production ON the droplet: infrastructure secrets are
# generated fresh here (never displayed, never stored locally), provider/R2/
# Bedrock keys are copied from the local .env. Refuses to overwrite an
# existing file. LEAN MODE (DEC-29/30): no Langfuse stack, Bedrock-hosted
# embed/rerank in ca-central-1.
#
#   deploy/make_server_env.sh root@<ip> http://<ip-or-domain>
set -euo pipefail
HOST="${1:?usage: deploy/make_server_env.sh root@<ip> http://<ip-or-domain>}"
SITE="${2:?usage: deploy/make_server_env.sh root@<ip> http://<ip-or-domain>}"

if ssh "$HOST" 'test -f /opt/hero/.env.production'; then
    echo "REFUSING: /opt/hero/.env.production already exists on $HOST" >&2
    echo "(rotate secrets deliberately via the runbook, not by re-running this)" >&2
    exit 1
fi

get() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }
gen() { openssl rand -hex 32; }

# Lean-mode inference is Workers AI (founder decision 2026-07-30, recorded
# INV-2 exception — see docs/residency.md). Needs a Workers-AI-scoped API
# token; the R2 S3 keys cannot call it. Account id derives from the R2 host.
CF_TOKEN="$(get CLOUDFLARE_API_TOKEN)"
if [ -z "$CF_TOKEN" ]; then
    echo "REFUSING: CLOUDFLARE_API_TOKEN missing from local .env" >&2
    echo "(mint one with Workers AI permission — the R2 keys cannot call Workers AI)" >&2
    exit 1
fi
CF_ACCOUNT_ID="$(get CLOUDFLARE_ACCOUNT_ID)"
if [ -z "$CF_ACCOUNT_ID" ]; then
    CF_ACCOUNT_ID="$(get R2_ENDPOINT | sed -E 's#https?://([a-f0-9]+)\.r2\.cloudflarestorage\.com.*#\1#')"
fi
if [ -z "$CF_ACCOUNT_ID" ]; then
    echo "REFUSING: cannot determine CLOUDFLARE_ACCOUNT_ID (not in .env, not derivable from R2_ENDPOINT)" >&2
    exit 1
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
chmod 600 "$TMP"

cat > "$TMP" <<EOF
# Hero.AI production env — generated $(date -u +%FT%TZ) by deploy/make_server_env.sh
# LEAN MODE (DEC-29/30). Infra secrets are machine-generated; see
# .env.production.example for docs.

# ── edge ──
SITE_ADDRESS=$SITE
ACME_EMAIL=$(get ACME_EMAIL)

# ── postgres ──
POSTGRES_USER=hero
POSTGRES_PASSWORD=$(gen)
POSTGRES_DB=hero

# ── R2 (INV-3; DEC-28 pilot exception) ──
R2_ENDPOINT=$(get R2_ENDPOINT)
R2_BUCKET=$(get R2_BUCKET)
R2_ACCESS_KEY_ID=$(get R2_ACCESS_KEY_ID)
R2_SECRET_ACCESS_KEY=$(get R2_SECRET_ACCESS_KEY)
R2_REGION=auto

# ── Lean-mode inference: Cloudflare Workers AI (recorded INV-2 exception,
# founder-approved 2026-07-30 pending DEC number — docs/residency.md).
# Bedrock ca-central-1 stays the INV-2-clean migration target (DEC-29). ──
CLOUDFLARE_ACCOUNT_ID=$CF_ACCOUNT_ID
CLOUDFLARE_API_TOKEN=$CF_TOKEN
BEDROCK_REGION=ca-central-1
AWS_BEARER_TOKEN_BEDROCK=$(get AWS_BEARER_TOKEN_BEDROCK)

# ── Langfuse: DEFERRED (DEC-30) — unset keys = tracing no-op ──
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=

# ── VLM routing (DEC-18) ──
VLM_MODEL_PRIMARY=claude-fable-5
VLM_MODEL_VERIFY=claude-sonnet-4-6
VLM_MODEL_FALLBACK=gpt-4o
VLM_MODEL_TRIAGE=
VLM_MODEL_CHAT=claude-haiku-4-5-20251001
ANTHROPIC_API_KEY=$(get ANTHROPIC_API_KEY)
OPENAI_API_KEY=$(get OPENAI_API_KEY)

# ── adapters (BL-19/H3 — lean selectors; cloudflare = Workers AI variant) ──
EMBEDDER_IMPL=cloudflare
RERANKER_IMPL=cloudflare
CALIBRATOR_IMPL=platt
VLM_IMPL=litellm

# ── auth (P4-1) ──
JWT_SECRET_KEY=$(gen)
JWT_EXPIRY_SECONDS=43200
# false until the HTTPS flip — Secure cookies never travel over plain
# http://<ip>; cockpit login would silently fail. Flip with the domain.
AUTH_COOKIE_SECURE=false
CORS_ORIGINS=$SITE

# ── public intake limits (BL-15) ──
PUBLIC_INTAKE_RATE_PER_HOUR=10
PUBLIC_PRESIGN_RATE_PER_HOUR=30
PUBLIC_ANSWER_RATE_PER_HOUR=20
PUBLIC_MESSAGE_RATE_PER_HOUR=60
PUBLIC_MAX_PHOTOS=6
PUBLIC_MAX_PHOTO_BYTES=10485760

# ── Nova (DEC-23/24) ──
NOVA_MAX_REPLY_TOKENS=300
NOVA_MAX_MESSAGES=30
NOVA_COST_CEILING_USD=0.25

# ── retrieval/verification ──
GROUNDING_THRESHOLD=0.8
GROUNDING_THRESHOLD_STRICT=1.0
MAX_CLARIFY_ROUNDS=3
MAX_CORRECTIVE_ROUNDS=2
CORRECTIVE_TIMEOUT_S=10.0
EOF

ssh "$HOST" 'mkdir -p /opt/hero'
scp -q "$TMP" "$HOST":/opt/hero/.env.production
ssh "$HOST" 'chmod 600 /opt/hero/.env.production'
echo "wrote $HOST:/opt/hero/.env.production (0600; secrets generated fresh, not displayed)"
