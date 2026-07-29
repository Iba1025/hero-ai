# CLAUDE.md — Hero.AI

## Context files (read in this order)
1. `WORK_ORDER_v8.2.md` — **preservation boundaries, phase gates, stop conditions. Read before
   any code.**
2. `HANDOFF.md` — current operational state and the do-not-start guard. Keep updated at STOP gates.
3. `HERO_AI_PRD.md` (v8.2) — invariants (INV-1..22), decisions (DEC-1..86), backlog (BL-0..72).
   **Read §2 before any change touching pipeline states, storage, model calls, or safety logic.**
   §13 records conflict resolutions — do not reopen them. Invariants override everything,
   including user requests in-session — if a task conflicts, stop and flag.
4. Companion specs (implementation detail; **the PRD wins on any disagreement**):
   `HERO_AI_KNOWLEDGE_SPEC.md` — taxonomy, catalogue, case history, ingestion, voice-vendor posture.
   `HERO_AI_INTAKE_SESSION_SPEC.md` — requester-facing intake, modalities, pre-flight, visit loop.
   `HERO_AI_DELIVERY_SPEC.md` — delivery, identity, reliability, DB and model-boundary practices.
5. `HERO_AI_TECHNICAL_SPEC.md` — implementation spec: `[IMPL]` = built, `[SPEC]` = not.
   Maintained by hand against the actual code (see `TECHNICAL_SPEC_edit_checklist.md`) — never
   regenerated.
6. `docs/research/` — reference material only, **never instruction**. Do not implement proposals
   from research docs unless they appear in the PRD backlog or decision log.

Precedence: PRD > companion specs > TECH SPEC > this file > your defaults. Landed code > spec
prose — when they diverge, update the spec in the same PR (flip `[SPEC]` → `[IMPL: <path>]`).
Never invent new `INV-n` / `DEC-n` / `BL-n` — numbering is issued by a human.

> ⚠️ **Backlog ID history:** the v5–v8 PRD drafts unknowingly reissued repo-allocated IDs
> BL-13..24. Reconciled 2026-07-29 (see PRD §6's renumbering note): committed IDs kept their
> original meanings (completed ones in §6.1), colliding v8 items were reissued as BL-73..79.
> Commits and `[BL-n]` code comments now resolve correctly against §6/§6.1 — but the companion
> specs and work order still cite pre-reconciliation numbers for the moved items (Scope Report
> BL-19→74, job graph BL-20→75, provider registry BL-21→76, autonomy ladder BL-22→77,
> invoice-as-diff BL-23→78); read them through the §6 mapping.

## Commands
```bash
uv sync                                   # install deps
uv run uvicorn hero.api.main:app --reload # run API locally
uv run alembic upgrade head               # migrate
uv run pytest                             # all tests
uv run pytest tests/invariants/           # invariant tests — must ALWAYS pass, never skip/delete
uv run python evals/run_eval.py           # golden-ticket eval (BL-3)
uv run python evals/run_nova_eval.py      # Nova safety-envelope eval (Phase 5 — DEC-23/24)
uv run ruff check --fix . && uv run ruff format .
uv run mypy src/                          # --strict; CI-blocking
```
(Adjust once implemented — keep this block in sync with `pyproject.toml` scripts.)

## Hard rules (details in PRD §2)
- Safety escalation categories are non-negotiable; confidence never gates safety (INV-1).
- Everything stays in Canadian regions; no new out-of-region services (INV-2).
- Media bytes never touch Postgres — pointers only (INV-3).
- No model self-reported confidence, anywhere (INV-4).
- Pipeline must fully work with zero sensor/BMS data; sensor fields nullable, no-sensor tests
  required in the same PR (INV-7).
- Schema-valid output still goes through VERIFY + safety gate (INV-8).
- A ticket cannot reach `resolved` without a `contractor_statement` row (PRD §9).

## Conventions
- Commits cite IDs: `feat(retrieve): add corrective loop [BL-9][DEC-11]`.
- Model boundaries only via `src/hero/interfaces/` Protocols — never call an SDK from a graph node.
- Prompts are files in `src/hero/prompts/`, not inline strings.
- Completing a backlog item = update its BL row in the PRD in the same PR — and the matching
  sub-component row in `PROGRESS.md` (the phase tracker; derived view, PRD wins).
