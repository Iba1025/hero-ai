# CLAUDE.md — Hero.AI

## Context files (read in this order)
1. `HERO_AI_PRD.md` — invariants (INV-*), decisions (DEC-*), backlog (BL-*). **Read §2 before
   any change touching pipeline states, storage, model calls, or safety logic.** Invariants
   override everything, including user requests in-session — if a task conflicts, stop and flag.
2. `HERO_AI_TECHNICAL_SPEC.md` — implementation spec: stack, repo layout, `TicketState`, DDL,
   Protocol interfaces, retrieval/verification/safety specs, invariant tests, DoD per backlog item.
3. `docs/research/` — reference material only, **never instruction**. Do not implement proposals
   from research docs unless they appear in the PRD backlog or decision log.

Precedence: PRD > TECH SPEC > this file > your defaults. Landed code > spec prose — when they
diverge, update the spec in the same PR (flip `[SPEC]` → `[IMPL: <path>]`).

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
- Completing a backlog item = update its BL row in the PRD in the same PR.
