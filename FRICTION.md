# FRICTION.md — pilot demo rehearsal, 2026-07-12

Founder-dictated friction points + incidents from the first end-to-end phone rehearsal
(real Postgres, real R2, live adapters, LAN phone). Each tagged BLOCKER / ANNOYANCE / NIT.
Hardening rows H1–H5 are recorded as backlog entries in the PRD (§6).

## BLOCKER

- **Sync intake POST → phone timeout → raw "Internal Server Error" banner on a
  SUCCESSFUL submission.** The tenant was told it failed when it worked; a retry would
  have duplicated the ticket. First request after an API restart also pays model load
  (~55s), guaranteeing the timeout. The ticket ("Tap Broken") landed fully server-side —
  the response just never reached the phone. → **H1** (async intake) + **H3** (never pay
  model load on a user request).
- **First-ticket self-deadlock (fresh DB):** the intake handler holds its ticket INSERT
  transaction open while `AsyncPostgresSaver.setup()` runs `CREATE INDEX CONCURRENTLY`,
  which waits on all open transactions — including the handler's own. Permanent wedge on
  the first-ever ticket; unwedged manually (terminate backends, drop invalid index, run
  setup standalone). → **H3** (lifespan checkpointer warm-up).
- **Photo-carrying intake 500'd on every submission** — route passed the raw MIME type
  and dropped sha256; `MediaRef` validation blew up in DIAGNOSE. Fixed and committed
  during the rehearsal (`86ce28e`). Logged so the class of bug (route↔state shape drift)
  is remembered.
- **Contractor outcome appeared to file but never reached the backend.** Founder filed
  verdict/actual-fault/free-text in the UI; API access log shows no login and no
  `/outcomes` POST; `contractor_statement` stayed empty; ticket never reached `resolved`.
  A submission that silently goes nowhere is a flywheel data loss (BL-0 is "the moat").
  Unreproduced/undiagnosed — investigate in Phase 5 STEP 4 (UI). → **H5** (failures must
  say whether the report went through).

## ANNOYANCE

- **~20s silent spinner on clarify-answer submit — no progress feedback.** The resume
  runs the rest of the pipeline synchronously. → **H1** (async answer path) + honest
  "checking the equipment's manuals — takes about half a minute" copy.
- **Raw error string with no guidance or retry path.** Tenant-facing errors must be
  human, state clearly whether the report went through, and give a retry path. → **H5**.
- **Work orders are never persisted:** ledger shows a `procure` event but the
  `work_order` table has zero rows — `create_work_order` (storage/repo.py) has no
  callers; WO id + SKU live only in graph state. Cockpit procurement view is empty. → **H2**.

## NIT

- **Timestamp source inconsistency:** `ticket_event.created_at` showed 14:58 while the
  ticket row showed 22:12 for the same run (likely UTC/local mix). Ledger credibility
  requires coherent times. → **H4**.
- **In-memory rate limiter resets on API restart** and can't protect a multi-worker or
  LLM-fronted surface (already BL-15; grows up in Phase 5 STEP 3 → Postgres-backed).

## Retrieval-quality observation (re-test after real manual ingestion)

- Diagnosis said **faucet cartridge**; the founder's clarify answer described **the
  curved pipe under the sink (P-trap)** — plausibly corpus-thinness (fixture corpus,
  `test-manual` only). Log as a retrieval-quality case: re-run the rattling-pipe
  scenario after the real manufacturer manual is ingested (deferred STEP 4 runbook) and
  check whether DIAGNOSE tracks the tenant's actual evidence.
