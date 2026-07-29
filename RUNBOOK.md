# RUNBOOK — Hero.AI pilot (Phase 6, DEC-27 lean mode)

> **Status: DRAFT 2026-07-29.** Written before the droplet loop has passed — steps marked
> ⏳ are specified but not yet executed against the box. Update each to ✅ with the date as
> the loop verifies them; this file is done when nothing is ⏳ (Phase 6 STEP 3 gate).

**The box:** DigitalOcean TOR1, `root@134.122.44.90`, Ubuntu 24.04, 4 GB (lean mode,
DEC-29/30). SSH key from the dev Mac. Stack: `caddy` (only public service, 80/443) →
`api` (FastAPI, no torch) + `postgres:16` + `qdrant`, all compose-internal.

---

## 1. Deploy (script + compose, by decision — DEC-27; CI deploys are BL-79)

```bash
# 0. once per box (ALREADY DONE on 134.122.44.90 — /root/bootstrap.done):
scp deploy/bootstrap.sh root@<ip>:/root/ && ssh root@<ip> 'bash /root/bootstrap.sh'

# 1. sync the tree (excluded-but-protected: server .env.production, data/)
deploy/push.sh root@<ip>

# 2. once per box: generate the server env (refuses to overwrite; rotation is §5)
#    ⚠️ requires in the LOCAL .env: R2_*, ANTHROPIC_API_KEY, OPENAI_API_KEY,
#    AWS_BEARER_TOKEN_BEDROCK (Bedrock lean mode), ACME_EMAIL (HTTPS flip only)
deploy/make_server_env.sh root@<ip> http://<ip>

# 3. build + start          ⏳ not yet run
ssh root@<ip> 'cd /opt/hero && docker compose --env-file .env.production up -d --build'

# 4. migrate                ⏳ not yet run
ssh root@<ip> 'cd /opt/hero && docker compose --env-file .env.production run --rm api alembic upgrade head'

# 5. ingest the corpus      ⏳ not yet run   (manuals live in /opt/hero/data/manuals — staged)
ssh root@<ip> 'cd /opt/hero && for m in \
  "test-manual:test_plumbing_manual.pdf:PL-2000" \
  "test-hvac-manual:test_hvac_manual.pdf:AC-3000" \
  "test-gas-manual:test_gas_manual.pdf:GF-8000"; do \
  IFS=: read -r id pdf code <<<"$m"; \
  docker compose --env-file .env.production run --rm api \
    python -m hero.ingestion ingest /manuals/$pdf --doc-id $id \
    --manufacturer ACME --model-codes $code --embedder bedrock_cohere; done'

# 6. smoke                  ⏳ not yet run
curl -fsS http://<ip>/health
# then: submit a chat ticket end-to-end through Caddy over http://<ip> and confirm it
# produces a diagnosis, hits the safety gate correctly, and writes a ledger entry.
# Off-corpus tickets CORRECTLY escalate diagnosis_unparseable (fixture corpus = 9 pts).
```

**Redeploy** = steps 1 → 3 → 4 (migrations are additive; `up -d --build` recreates only
changed services). **Never** run `make_server_env.sh` on a box that has an env — it refuses,
and that refusal is load-bearing.

## 2. Gotchas that already bit us (do not relearn)

- **Docker publishes ports BYPASSING ufw.** Only caddy may publish. Adding a `ports:` line
  to postgres/qdrant silently punches through the firewall.
- **`AUTH_COOKIE_SECURE=false` until the HTTPS flip** — Secure cookies never travel over
  `http://<ip>`; cockpit login silently fails, no error anywhere.
- **Qdrant storage must be durable** (named volume `qdrant_storage`). The 2026-07-13 local
  incident: Qdrant run from `/tmp`, macOS purged the collections. Recovery = re-ingestion
  (idempotent on `(doc_id, page)`), then `check_index_integrity` + `bm25_canary`.
- **BM25 tokenizer is version-stamped** (`sha1-tf-v1`); the integrity canary guards it.
  If retrieval quality craters silently, run the canary before anything else.
- **The dev Mac's rsync is openrsync** — `deploy/push.sh` must stay `--stats`-only
  (no `--info=`), or pushes fail with a usage error.

## 3. Backups + restore drill (Phase 6 STEP 3) ⏳ NOT YET IMPLEMENTED

A backup that hasn't been restored isn't a backup. The drill is part of setup, not a
follow-up.

```bash
# postgres — nightly at 03:15 EST, keep 14, to /root/backups (cron on the box)
docker compose --env-file .env.production exec -T postgres \
  pg_dump -U hero -Fc hero > /root/backups/hero_$(date +%F).dump

# qdrant — nightly snapshot per collection via the internal API
docker compose --env-file .env.production exec -T qdrant \
  sh -c 'wget -qO- --post-data="" http://localhost:6333/collections/manuals/snapshots'

# RESTORE DRILL (run once now, then quarterly; record the date below):
#   1. scratch database:  createdb hero_drill && pg_restore -d hero_drill <dump>
#   2. row-count sanity vs live (tickets, ticket_event, contractor_statement)
#   3. qdrant: recover snapshot into a scratch collection, run bm25_canary against it
# Last drill: NEVER ❌
```

Media (R2) is not backed up here — pointers only in Postgres (INV-3); R2 versioning is the
media story until the DEC-28 migration.

## 4. Uptime check ⏳ NOT YET IMPLEMENTED

`GET /health` is deliberately shallow (liveness only; dependency health is proven by smoke
tests). External monitor (UptimeRobot-class, 1-min interval) on `http://<ip>/health` →
founder's phone. Compose healthchecks restart wedged services on-box.

## 5. Secret rotation

Edit `/opt/hero/.env.production` on the box (0600), then
`docker compose --env-file .env.production up -d` to re-read. Postgres password rotation
additionally needs `ALTER ROLE hero PASSWORD ...` before the restart. JWT rotation logs
everyone out — do it in a quiet window.

## 6. When it breaks at 2am

| Symptom | First move |
|---|---|
| 502 from caddy | `docker compose ps` — is api healthy? `docker compose logs api --tail 50` |
| Login silently bounces | Check `AUTH_COOKIE_SECURE` vs scheme (§2) |
| Tickets stuck `queued` | api logs; startup recovery re-drives runs on restart (H3) |
| Retrieval suddenly bad | `bm25_canary` / `check_index_integrity` (§2) |
| Disk full | `docker system prune -f` (images), check `/root/backups` retention |
| Box unreachable | DO console → reboot; compose has `restart: unless-stopped` |

**Never** bypass `_ResumeGuardedGraph`, weaken an invariant test, or hand-edit prod data
to unstick a ticket — escalate to the founder instead (work order §6).
