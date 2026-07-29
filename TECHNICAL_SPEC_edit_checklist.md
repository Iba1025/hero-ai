# HERO_AI_TECHNICAL_SPEC.md — edit checklist

**This file is NOT regenerated. It is yours.**

`HERO_AI_TECHNICAL_SPEC.md` records what is actually built in your repo via `[IMPL]` / `[SPEC]`
tags. I read it only partially, and regenerating it from that would produce a file that **lies to
Claude Code about what exists** — claiming things are built that aren't, or the reverse. That is the
one document in the set where a confident guess is worse than nothing.

Below is what to add to it yourself, or what to have Claude Code add after it has read the actual
code (Phase 1 of the work order is a natural time).

---

## 1. Mark everything new as `[SPEC]`

Every item below is unbuilt. Tag accordingly, so Claude Code never assumes otherwise.

**Graphs and sessions**
- `[SPEC]` Job graph — `PRELIM_SCOPE → MATCH → ASSIGN_VISIT → MOBILISE → VISIT → …` (PRD §3.2)
- `[SPEC]` `_JobResumeGuard` — the job graph's single resume path
- `[SPEC]` `DiagnosisReady` typed handoff event (no shared checkpoint, INV-12)
- `[SPEC]` Capture session — bounded activity, **not a graph** (DEC-45)
- `[SPEC]` Pre-flight triage — standalone classification, **not a graph state** (DEC-55)

**Pipeline deltas** (existing states — mark the *additions* as `[SPEC]`, keep the state itself `[IMPL]`)
- `[SPEC]` `TRIAGE` emits `client_class` (DEC-69)
- `[SPEC]` `RESOLVE` emits `scope_report` with `kind='preliminary'` (DEC-56)
- `[SPEC]` `PROCURE` output reshaped to truck manifest (DEC-32) — **the only changed output contract**
- `[SPEC]` `INTAKE` accepts capture-session artifacts (INV-14)

**New modules**
- `[SPEC]` Identity layer — `party_identifier`, `conversation`, `party_attribute` (DEC-63)
- `[SPEC]` Delivery layer — webhook receivers, queues, coalescing (DEC-57..61)
- `[SPEC]` Knowledge/catalogue — `task_taxonomy`, `vendor_catalog_item`, `case_record` (DEC-82..86)
- `[SPEC]` Visit model — `provider_capacity`, `visit` (DEC-51/53)
- `[SPEC]` Company assistant — `contractor_assistant` (DEC-77/80)
- `[SPEC]` Commercial fork — `rfq`, `rfq_recipient` (DEC-70)
- `[SPEC]` Distribution surface — `contractor_profile`, `embed_config` (DEC-66/67)

---

## 2. Confirm what is already `[IMPL]` and freeze it

These should already be marked built. Verify, and add a **DO NOT MODIFY** note against each —
they're §1 of the work order:

- Ticket graph topology `INTAKE → … → OUTCOME`
- `_ResumeGuardedGraph` and the single resume path
- Async execution (H1)
- LangGraph Postgres checkpointer
- `VERIFY` / `SAFETY_GATE` logic
- ColQwen multivector retrieval + BM25 RRF fusion
- **BM25 stable hashlib tokenizer** + integrity canary
- Nova chat intake, operator ledger, contractor outcome screen

---

## 3. Add a §5 schema section if one doesn't exist

The PRD §14 lists table names and key columns; the technical spec should hold the **actual DDL**.
Bundle boundaries matter more than completeness here — mark which tables land in the Phase 2 schema
bundle (work order §4), because they are each other's foreign keys:

```
task_taxonomy · task_alias · party_identifier · site · party_role
provider · provider_network · network_id columns
ticket.building_id → NULLABLE · ticket.equipment_id · ticket.site_id · equipment
```

---

## 4. Add a residency table

Referenced by INV-2 and DEC-29/33/46/81, and by the work order's Phase 1. If `docs/residency.md`
doesn't exist yet, either create it or fold it in here:

| Service | Purpose | Region | Data crossing | Retention | Mitigation | Reviewed |
|---|---|---|---|---|---|---|
| Embedder (API) | Ingestion + query | ? | Manual pages, query text | ? | DEC-29 | ? |
| Reranker (API) | Retrieval | ? | Query + candidate text | ? | DEC-29 | ? |
| Twilio | SMS/voice transit | US1 | Message bodies, call audio | **Redaction on, recording off** | DEC-81 | ? |
| ElevenLabs | TTS only | EU | Templated outbound text | **ZRM** | DEC-81 | ? |
| ASR | Speech → text | **self-hosted** | Requester speech | n/a | DEC-81 | ? |
| R2 | Media | NA hint, **no CA guarantee** | Photos, video, keyframes | — | **DEC-28 open risk** | ? |

The startup guard asserts config matches this table.

---

## 5. Correct one thing the PRD gets wrong by implication

The PRD repeatedly says **"migration 1."** You are past `0009`. It does **not** mean migration
`0001` — it means those items are expensive to retrofit and must land **together in one bundle**.
Make that explicit wherever the technical spec references migrations, so nobody reads it as a
directive to rewrite history.
