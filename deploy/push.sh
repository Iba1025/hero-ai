#!/usr/bin/env bash
# Sync the working tree to the droplet (pilot deploys are rsync-based by
# decision, DEC-27; CI-driven deploys are BL-24, post-pilot).
#
#   deploy/push.sh root@<ip>
set -euo pipefail
HOST="${1:?usage: deploy/push.sh root@<ip>}"

# Excluded-but-protected (--delete does not touch excluded paths): the
# server's .env.production and data/manuals survive every push.
# --stats, not --info=stats1: macOS ships openrsync, which lacks --info
# (this is why the first push never happened from the dev Mac).
rsync -az --delete --stats \
    --exclude .git \
    --exclude .venv \
    --exclude node_modules \
    --exclude web/node_modules \
    --exclude web/dist \
    --exclude .env \
    --exclude '.env.production' \
    --exclude data/ \
    --exclude design/ \
    --exclude .mypy_cache \
    --exclude .ruff_cache \
    --exclude .pytest_cache \
    --exclude '__pycache__' \
    --exclude '.DS_Store' \
    ./ "$HOST":/opt/hero/
