# Hero.AI — Delivery, Identity & Reliability Spec

**2026-07-27 · Companion to PRD v8.1 · Supersedes PRD_V7_AMENDMENTS (invariants and decisions now
live in the PRD; this file keeps the implementation detail)**

> **Status:** implementation detail. **The PRD is the index of truth** — if this file disagrees, the
> PRD wins.
> **Governed by:** INV-2, INV-3, INV-11, INV-15, INV-17, INV-18, INV-19, INV-20 ·
> DEC-57 through DEC-64.
>
> **Provenance:** patterns from an architectural review of IRIS (Nvestiv comms layer, S. Hassan).
> Patterns only — no code, no vendors, no product logic (§8).

This is the layer between *"an agent decided something"* and *"a human actually received it."* It is
where communications products actually fail, and Hero has almost none of it built.

---

## 1. Webhook receivers (DEC-57)

**Verify → enqueue → ack. Nothing else in the request path.**

Every vendor retries on slow acks, so doing work in the handler causes a self-inflicted retry storm —
a failure that compounds under exactly the load you least want it under.

- **Signature verification per vendor, against the vendor's actual documented scheme.** Never
  assumed. IRIS's email vendor signed via Svix's `{id}.{timestamp}.{body}` construction; a naive HMAC
  implementation would have silently rejected 100% of real deliveries while passing every test.
- **Per-route body limits enforced *before* the body is buffered.** Closes a memory-exhaustion hole.
  Plus a catch-all cap on `/webhooks/*` so a future route can't ship uncapped.
- Route-specific ceilings: telephony and ASR callbacks are small; media and email with inline base64
  legitimately exceed 1 MiB.
- Ack fast, always. All work happens on a queue.

```
POST /webhooks/{vendor}
  → body-limit check (pre-buffer)
  → signature verify (vendor-specific)
  → enqueue {raw_payload}          ← stage-first (§3)
  → 200
```

---

## 2. Queues (DEC-58)

Separate concurrency pools, each with a written rationale, each env-overridable.

| Pool | Contents | Why it's separate |
|---|---|---|
| `live` | Interview turns, hazard classification, session responses | **A human is mid-sentence.** <700ms budget |
| `dispatch` | Match, provider notification, requester confirmation | Human waiting, not real-time |
| `ingest` | Ticket creation, artifact persistence, webhook drain | Protects the Postgres pool |
| `pipeline` | Retrieve, diagnose, verify, scope | Seconds-to-minutes, nobody watching |
| `batch` | Corpus ingestion, flywheel scans, calibration, reconciles | Nobody watching, ever |

The <700ms conversational budget (DEC-52) makes this mandatory rather than tidy. **Corpus ingestion
must never be able to delay a live interview turn.** Cheap to specify now, expensive to retrofit once
tasks are written.

---

## 3. The failed-and-notified bar (DEC-59)

**Every inbound interaction ends processed-and-answered or failed-and-notified. Never silently
dropped.**

### 3.1 Terminal vs transient, in the type system

```python
class TerminalFailure(BaseModel):   # retrying fails identically — tell the human NOW
    reason: str
    human_copy: str

# transient failures THROW — the runner retries
```

| Failure | Class | Behaviour |
|---|---|---|
| Blurry frame, unsupported format, unplayable audio | **Terminal** | *"That one's a bit blurry — mind retaking it?"* immediately |
| VLM 503, timeout, rate limit, network blip | **Transient** | Throw, retry silently |

Without this split, terminal failures burn every retry and delay the *"please re-shoot that"* by
minutes.

### 3.2 One shared human-facing terminal path

Ingest-side and processing-side failures produce **identical copy**, and the wording never explains
vendor internals to a requester.

### 3.3 Stage-first ledgers

**Persist the staging row from the raw payload alone, before any fallible work** — identity
resolution, media fetch, model call — with enrichment columns nullable and attached later.

While staging required resolution first, a fault in that window left **no row at all**: the vendor had
its 200 and wouldn't redeliver, the sweep's selector was the table itself, and no diagnostic could
ever observe the loss.

INV-14 already requires artifacts to persist on hazard termination. **This extends the same guarantee
to infrastructure failure, and the ordering — payload-only insert first — is the entire mechanism.**

Applies to `capture_session`, `capture_artifact`, and inbound webhook payloads. Pair with retention:
staging ledgers swept on a bounded horizon so the INV-20 monitors read a recent window.

### 3.4 Failure-rate monitors (INV-20)

Per processor. **The hazard classifier's monitor alerts, not just logs.**

Discriminator: genuine bad input is rare and uncorrelated; a dead dependency fails everything
identically, at once. Alert on proportion over a rolling window, not on events.

---

## 4. Message coalescing (DEC-60)

A stressed requester sends five fragments in forty seconds. A naive agent answers the first one
mid-thought and burns turns of a five-minute budget on noise.

```
new message → reset quiet window (5s)
            → hard ceiling 30s (a chatty person always hears back)
            → max-resets cap
            → message landing mid-compose ABORTS it and resets, unless cap tripped
```

**The reset/commit decision is isolated in one pure function** so it is unit-testable rather than
emergent.

> ⚠️ **Sits strictly BELOW hazard classification. INV-15 runs per message, before batching.**
> Someone typing *"wait I smell gas"* as fragment three of five must interrupt on arrival, not after
> the quiet window settles. Coalescing applies to interview turn policy priorities 2–7 only.

Scope: text and SMS turns. The live voice session is turn-based and does not debounce.

---

## 5. Per-turn transcript validation (DEC-61)

**A call cannot be re-fetched. It is unrepeatable evidence.**

- One malformed turn drops **that turn**, loudly — never the whole call.
- **An unknown speaker role is dropped, never defaulted.** There is no honest default: a wrong one
  silently files the agent's own words, or a tool trace, as things the requester said. Those become
  evidence artifacts feeding `DIAGNOSE`. *"The tenant said the breaker was already reset"* versus
  *"the agent asked whether it was"* is a diagnostic difference with a truck roll attached.
- Deterministic per-turn external refs make webhook redelivery a no-op.

---

## 6. Vendor-hosted config drift (DEC-62)

Where an agent's prompt or persona lives in a vendor dashboard, it forks from the repo the moment
anyone edits it, and the phone personality silently diverges from the text personality.

- The objective lives in the repo
- A reconciliation script pushes it
- A startup/CI drift check fails the build on divergence

**Rule, carried verbatim: anything that changes what the agent is trying to learn belongs in the
shared objective, never in per-channel framing.** Per-channel framing may only change *format*. That
is the enforcement mechanism for "same questions, different modality" — and for INV-22c, where the
contractor owns identity and policies but never the protocol.

Applies to `contractor_assistant` config (DEC-78): the policies quoted to a requester are commercial
commitments and must be auditable.

---

## 7. Identity and conversations (DEC-63, DEC-64)

### 7.1 Why this is the highest-priority structural item

Hero has **no identity resolution layer**, and needs one more than a CRM does:

- Providers onboard by phone — no account, no email
- Requesters file tickets with no account, no app, no portal
- The coordinator agent calls suppliers and subs outbound

Every one of those arrives as a bare phone number or email that must resolve to exactly one party.
**Without it the provider registry fragments into duplicates and `provider_metric` — the ranking that
drives matching — accumulates against ghosts.**

§10.1 already warns relationship schema is expensive to retrofit. **Migration-1 item.**

### 7.2 Schema

```sql
party_identifier
  party_type      -- requester | provider | coordinator | supplier
  party_id
  type            -- phone | email
  value           -- NORMALIZED: E.164 / lowercased
  verified, created_at
  UNIQUE (type, value)        -- this constraint IS the concurrency control

conversation
  party_id, channel, vendor_external_ref, state,      -- open | closed
  opened_at, closed_at
  UNIQUE (channel, vendor_external_ref)

conversation_message
  conversation_id, speaker,   -- party | agent  (NEVER defaulted — DEC-61)
  text, timestamp, external_ref
  UNIQUE (conversation_id, external_ref)

party_attribute               -- accumulate, never overwrite
  party_id, key, value, source_conversation_id, observed_at
```

### 7.3 Three non-optional practices

**Normalize before every write.** E.164 via libphonenumber with channel-prefix stripping; lowercased
email. *"Exact match"* is meaningless without canonicalization — `4165550100`, `+14165550100`,
`+1 416 555 0100`, and `(416) 555-0100` must collapse to one provider.

**Race-safe creation by constraint, not by lock.** Two concurrent inbound events for the same unknown
person both race the unique insert; the loser adopts the winner's party. Correctness becomes
independent of worker concurrency settings.

**Anonymous path.** A caller with withheld ID still gets their interaction stored against a
review-flagged party with no identifier. **A tenant calling from a blocked number does not lose their
ticket.**

### 7.4 Conversations as first-class objects

`job_event` (INV-11) is an event ledger, not a conversation model. Both are needed, because a single
intake spans a voice session and a follow-up text.

One `getPartyTimeline` read serves the coordinator UI, the Twenty front component (BL-32), and the
agent's prompt assembly — same shape as the Scope Report: Hero owns, Twenty renders.

### 7.5 Confidentiality guard (DEC-64)

**If the freshly-resolved party and the conversation's stored party disagree, refuse the write and
dead-letter for human review.** Never file one person's words under another's record.

IRIS's trigger case: a CC'd colleague replying on a thread keyed to the original sender — the
extractor then wrote person A's goals onto person B's record and fed A's private history into B's
prompt.

**Hero's equivalents are routine:** a sub replying on a GC's email thread; a second tech texting from
a job site; a tenant using the building manager's phone.

In a network where provider terms are confidential to the coordinator (§10.1's data clause),
cross-filing is a **confidentiality breach, not a bug.**

### 7.6 Accumulate with provenance

`party_attribute` rows accumulate and are never overwritten; each cites its source conversation. This
is Hero's evidence-chain ethos applied to relationship data, and the right shape for §4.5.3's *"enrich
per job, infer from behaviour"* registry — rate structures as timestamped entries that supersede
rather than a mutable column; job-size-band inferences that cite the job that taught them. Each is
then a flywheel label with provenance, exactly like a manifest edit.

---

## 8. Database practices

### 8.1 Grant hygiene as invariant tests (BL-42, ~1 day)

**Postgres grants `EXECUTE` to `PUBLIC` by default on new functions. Granting to a role is additive,
not exclusive.** A `SECURITY DEFINER` RPC therefore becomes callable by anyone holding the anon key —
bypassing RLS and rendering every upstream signature check moot.

PRD §14 states `job_event`, `live_hazard_event`, and `dead_letter` are *"append-only, enforced by
grants not convention."* **This is precisely the class of mistake that silently voids that claim**,
and Hero's stakes are higher than a CRM's: those tables are the dispute defence and the life-safety
record.

Ship as **tests, not migrations** (fits `tests/invariants/`), so a future migration that forgets
fails CI:
- For every function: `REVOKE ... FROM PUBLIC`, `search_path` pinned, `EXECUTE` granted only to the
  service role
- For append-only tables: assert `UPDATE`/`DELETE` are revoked

### 8.2 Insert flags are not completion signals (BL-43)

Treating an upsert result as *"the work happened"* means a retry after partial progress reports
success while permanently losing the side effect. IRIS's instance: a retry after a failed send
skipped the reply entirely — green run, no dead letter, and a person who never heard back.

**Rule: at every idempotent boundary, ask whether the work happened by querying current state, never
by trusting this attempt's insert flag.**

Hero's boundaries: `OUTCOME` label capture · dispatch notification · requester confirmation · invoice
emission · Twenty push · RFQ solicitation.

*"The row already existed"* must never be read as *"and its downstream effects already happened."*

### 8.3 Atomic join-or-open with advisory locks

IRIS measured five concurrent messages splitting one thread into five conversations — every worker
read before any wrote. Fixed with one SQL function holding `pg_advisory_xact_lock` on the natural key.

Hero's collision cases are identical in shape: two capture events for the same equipment ·
simultaneous ticket creation from a session and a follow-up text · concurrent holds against the same
capacity window.

Replace read-then-insert with one atomic locked function returning the row either way.

### 8.4 Dead letters, fail-closed config, three-valued liveness (BL-46)

**Dead-letter capture as a global failure hook.** Task runners intercept exceptions to drive retries,
which swallows unhandled ones — a run that exhausts retries otherwise vanishes silently. LangGraph
checkpoints (INV-6) preserve state but not the *"this ticket died, here's the payload"* record. One
table plus one hook; aligns with INV-11.

**Fail-closed configuration.** IRIS was burned twice: `Number("")` → `0` silently zeroing a session
window, and a self-recognition check that failed open — nearly making the agent reply to itself in a
loop. Hero's residency startup guard (INV-2) is the right instinct; extend it to validate every
operationally-meaningful env var (present, parseable, in range) and make identity/self-recognition
checks **throw when unconfigured**. Same class as the `server_default="now()"` bug, in config instead
of DDL.

**Three-valued liveness.** Ask the runner *"is this run alive?"* and accept `alive | dead | unknown` —
never bucket a network blip as dead. **The job graph parks for hours-to-weeks on approvals**, so a
wedged approval is invisible without this. A `_JobResumeGuard` companion sweep distinguishing
*"legitimately waiting"* from *"wedged"* belongs in BL-20's definition of done.

### 8.5 Sync-layer hardening (BL-48, part of BL-31's DoD)

- **Idempotency by constraint** — every Hero→Twenty and Twenty→Hero write goes through a natural key;
  redelivery is a database no-op.
- **Reconcile sweep** — a scheduled diff of recently-changed objects on both sides against
  `crm_sync_state`. *"The webhook silently stopped firing"* is a failure only a periodic reconcile
  detects. Safe to run blindly at any time because every write is idempotent.

---

## 9. Model-boundary practices

### 9.1 Stop-reason allowlist (INV-19, BL-50, ~1 day)

Any finish-reason other than a clean stop → **raise, retry, dead-letter. Never parse a fragment.**

One place: the LiteLLM adapter. This is an INV-8 sibling — a truncated `DIAGNOSE` that happens to be
schema-valid is exactly the *"schema-valid ≠ correct"* case, and **a truncated hypothesis list
silently narrows the conformal set**, quietly voiding BL-10's safety property with no error anywhere.

Corollary: `max_tokens` are documented constants with headroom. A ceiling is not a reservation;
billing follows actual tokens. Budget exhaustion manifests as silence or fragments, never as an
exception.

### 9.2 Injection suites (INV-18, BL-49, ~3 days)

**Retrieved and inbound content is data, never instruction.** Hero's exposure is broader than a chat
product's: manufacturer PDFs we didn't author, requester speech, OCR'd nameplate text, and video
transcripts all flow into prompts for agents that drive **real-world physical action**.

Suite per agent surface: intake agent · operator copilot · coordinator agent. Natural companion to
BL-30's hazard red team.

### 9.3 Closed-vocabulary extraction (into BL-18)

- **Closed enum** of fact types — open vocabularies make eval and filtering impossible
- **Only what was actually stated.** *"Do not infer a goal from a job title"* → **Hero: do not infer a
  fault from an equipment model**
- One fact per entry
- **Each value self-contained enough to read months later**, with a provenance pointer:
  *"Breaker for the kitchen circuit trips within 30 seconds of running the microwave"*, not
  *"electrical issue"*

That last rule is what makes extracted context usable as flywheel data rather than prose.

### 9.4 Prompt-assembly hygiene (into BL-18, BL-24)

- **Annotate only when the annotation is real.** Channel or modality tags appear only when the window
  actually spans channels or modalities — otherwise the model learns to emit the scaffolding in its
  own output. Plus an explicit never-echo instruction.
- **Trim context windows to well-formed boundaries** — both ends to party turns, so the model never
  sees a window opening or closing mid-exchange.
- **Name every model binding by intent**, alongside the residency record (`docs/residency.md`).

---

## 10. Do not import

Four source-system choices would violate Hero invariants. Recorded so they aren't re-proposed.

1. **The vendor stack.** ElevenLabs, AgentMail, Gemini + Google Search — none established
   CA-resident. INV-2 (as amended by DEC-33/46) makes it a hard gate. Import the patterns, keep
   vendors behind the existing Protocol seams, record every choice in `docs/residency.md`.
2. **Autonomous replying.** The source composes and sends with no human gate. Hero's autonomy ladder
   (DEC-42) starts every action type at L1 draft and earns promotion by measured edit rate. **The
   compose loop is the right machinery; the send authority is not.**
3. **Live web grounding in replies.** Correct for a networking concierge. For Hero it's an
   INV-9/INV-4 hazard — an agent citing a live search result sounds exactly like an authoritative
   diagnosis — and an INV-2 problem. **Keep only the anti-fabrication contract** (never state a
   figure from memory as current; *"I can't pull that — a human will follow up"*).
4. **Answer-every-message discipline.** Their debounce ceiling guarantees a reply within ~30s. INV-15
   is the opposite: hazards interrupt immediately, mid-burst, no coalescing (§4).

---

## 11. Build order

**BL-42 → BL-47 → BL-49 / BL-50 → BL-45 (with BL-30) → BL-43 → BL-46 → BL-51 → BL-44 → BL-48.**

- **BL-42** is a day and closes a security-hole class that silently voids §14's enforcement.
- **BL-47** is schema-shaped; §10.1 warns relationship schema is expensive to retrofit — it belongs in
  the same migration as provider↔network many-to-many.
- **BL-49 / BL-50** are cheap and harden surfaces you're about to build.
- **BL-45 ships *with* BL-30**, not after — an unmonitored safety classifier is a safety gap, not a
  partially-complete feature.
- Everything after is design-doc material until the interaction plane is being built.
