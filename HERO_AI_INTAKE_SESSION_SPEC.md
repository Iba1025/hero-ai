# Hero.AI — Intake Session Spec (v3)

**2026-07-27 · Companion to PRD v8.1 · Supersedes v2**

> **Status:** implementation detail. **The PRD is the index of truth for invariants, decisions, and
> backlog** — if this file disagrees with it, the PRD wins.
> **Governed by:** INV-1, INV-9, INV-11, INV-12, INV-14, INV-15, INV-16, INV-22 ·
> DEC-45, 51–56, 60, 75–80.

---

## 1. What this describes

The requester-facing intake — a conversation that gathers evidence and ends with a **confirmed
diagnostic visit** (residential) or a **quote request** (commercial). One implementation, three
capture modalities, one terminal fork.

**The visit is a product contractors already sell.** Shane: *"$199. First hour of work... I'm
thinking I might up the price to 249."* Tyler: *"Oftentimes I will charge for those and then say,
should we secure the contract, that will be credited back."* We aren't asking anyone to trust an AI
diagnosis — we're making their existing paid first step shorter and better-equipped.

---

## 2. Who the requester is talking to

**The company's assistant, in a neutral Hero voice (DEC-77, DEC-80).**

> *"Hi, you've reached New Toronto Electric — I'm their assistant. Can you tell me what's going on?"*

That sentence is simultaneously the branding and the disclosure (INV-22).

**Named for the registered business, never for an individual (DEC-80).** Not *"Shane's assistant"*.
Naming an owner to a stranger is a privacy call that isn't ours; it misrepresents firms with partners
(Tyler works with Dimitri); it breaks when staff change or the business sells; and it reads wrong
above a two-person shop.

❌ **No voice cloning of any real person, ever (DEC-79, INV-22a).** The trust signal is the name, not
the timbre.

**Hero owns the protocol; the contractor owns identity and policies (INV-22c):**

| Hero's — identical everywhere | Contractor's — varies |
|---|---|
| Questions asked (§4) | Registered business name |
| Hazard behaviour, escalation | Tone preset (warm / brisk / plainspoken) |
| Permitted-actions allow-list | Greeting and sign-off |
| Evidence structure | Policies — diagnostic fee, flat-vs-hourly, service area, hours, exclusions |
| Visit-vs-repair language | Callback promise wording |

A contractor may **never** configure what the agent asks, what it escalates, or what it permits a
requester to touch.

---

## 3. Three modalities (DEC-75)

**Live video is an option, never a requirement.** Forcing it kills completion rate, and completion
rate gates the whole session.

| Mode | Voice | Video | Photos | Ships |
|---|---|---|---|---|
| **Text + photos** | ❌ | ❌ | ✅ upload | **First** — today's stack, no residency blocker |
| **Voice + photos** | ✅ | ❌ | ✅ upload | Second — needs CA-resident TTS/ASR |
| **Voice + live video** | ✅ | ✅ | ✅ | Last — needs BL-28, BL-30, BL-40 |

**Identical in all three:** the interview protocol · the pre-flight gate · the visit offer and
read-back · the Scope Report · the safety gate · INV-15.

**Only the mechanism differs:**

| Live video does it by… | Photo mode does it by… |
|---|---|
| Frame-quality gate: *"hold steady, move closer"* | Quality check on upload → *"that one's blurry, mind retaking it?"* |
| Nameplate detector spots it in frame | OCR on each upload; agent asks for the sticker explicitly |
| Agent guides a pan for spatial context | Agent requests specific shots — *"one of the unit, one of the wall behind it"* |
| Agent observes an isolation test | Requester reports it — *"okay, flip it and tell me what happens"* |
| Hazard detector watches continuously | Hazard classification on **speech + each uploaded photo** |

> ⚠️ **Photo mode escalates on weaker evidence, not stronger (DEC-76).** No motion, no continuous
> view, no audio of a hissing line. **Fewer signals must never read as fewer hazards.** BL-30
> red-teams both modes separately.

**Mode is switchable mid-session in either direction**, without losing turns or artifacts. Bandwidth
collapse auto-degrades video → photos. The requester can also just turn video off.

---

## 4. The interview

Shane's protocol, automated. Same questions in every mode.

- **Timeline** — when it started, constant or intermittent, worsening
- **Recent changes** — highest-signal question, and the one nobody asks. *"It happened after such and
  such came and drilled a pin for a painting. Could have drove into the wire."*
- **Isolation already attempted** — breakers checked, valve shut, unit reset, filter changed
- **Environmental context** — which unit/floor/zone, what's above and beside
- **Equipment identity** — make, model, serial (BL-28)
- **Guided capture** — what to show, and **what not to attempt**

**Hard cap: 5 minutes.** Shane: *"we need to be quick."* No account, no app, no portal.
Never instruct a requester onto a roof, into a panel, or under a unit.

### Turn policy — priority order, evaluated every turn

1. **Hazard signal → INV-15 interrupt.** Terminate, escalate. Nothing else runs.
2. Capture quality bad with a capture pending → correction prompt
3. Nameplate missing on nameplate-bearing equipment → guide to it
4. Protocol gap → next unanswered question
5. Permitted isolation test available → **allow-list only**
6. Protocol covered → pre-flight (§5)
7. Idle → acknowledge, wait

One question per turn. Never a fault, cause, part, price, or repair instruction (INV-14).

> ⚠️ **Message coalescing (DEC-60) sits BELOW priority 1.** A stressed requester sends five fragments
> in forty seconds; the debounce answers the burst rather than the first fragment. **But INV-15 runs
> per message, before batching.** Someone typing *"wait I smell gas"* as fragment three must
> interrupt on arrival, not after the quiet window settles.

**Permitted actions allow-list** (`safety/permitted_actions.py`): reset a breaker · change a
thermostat setpoint · replace a filter · run a fixture.
**Never:** open a panel · bypass a safety · relight a pilot · touch a gas line · access a roof ·
enter a crawlspace · approach anything smoking, sparking, or wet.

**Durability rule:** every turn writes artifacts immediately. A session abandoned at turn 4 is a
valid ticket with four turns of evidence and recorded gaps. **Partial work is never lost** — the most
important anti-drop-off property in the system.

---

## 5. Pre-flight triage (DEC-55)

In-session, in a conversational pause, target <2s. **Not a graph state** — a standalone read-only
classification reusing `safety/hazards.py` and the TRIAGE classifier, so it and `SAFETY_GATE` cannot
disagree unsafely (INV-12 preserved).

```python
class PreFlight(BaseModel):
    hazard: bool                  # deterministic rules FIRST, then classifier
    hazard_reason: str | None
    trade: TradeCategory
    client_class: Literal["residential", "commercial"]   # DEC-69
    urgency: Literal["emergency", "urgent", "routine"]
    confidence_sufficient_for_visit: bool
```

| Outcome | Behaviour |
|---|---|
| **Hazard** | No offer. *"This needs a licensed [trade] right away. I'm arranging that now — someone will call you within [X]. In the meantime, [safety instruction]."* → hard-escalate |
| **Emergency, non-hazard** | Skip windows, route to a live dispatcher. Don't offer Thursday to a burst pipe |
| **Clear + residential** | → visit offer (§6) |
| **Clear + commercial** | → RFQ draft (§9) |

**Asymmetry rule (INV-16):** pre-flight may only ever be *more* conservative than `SAFETY_GATE`. It
can block a visit that would've been fine. It can never permit one the gate would refuse.

---

## 6. Visit offer and confirm loop (residential)

Two-step confirm. The read-back is a commitment device and reduces no-shows.

> **Assistant:** "Good — I've got what I need for now. To get you sorted, a technician needs to come
> take a look. I can do Thursday morning between 8 and 10, or Friday afternoon between 1 and 3."
>
> **Requester:** "Thursday."
>
> **Assistant:** "Thursday the 30th, 8 to 10am, at 42 Wellesley, unit 1204 — is that right?"
>
> **Requester:** "Yes."
>
> **Assistant:** "Confirmed. You'll get a text with the details. Before they arrive I'll send them
> everything we captured — the photos, the model number, what you told me — so they turn up knowing
> what they're walking into. [Fee disclosure.] If anything we find suggests this needs a specialist
> instead, we'll call you before Thursday."

Five things doing work:

- **"take a look"**, not *"fix it"* — a visit, not a job (INV-16)
- **read-back with address** — commitment plus error catch
- **why it helps them** — the tech arrives informed
- **fee disclosure** from the contractor's policy config — a surprise fee at the door is the fastest
  way to destroy trust in this business
- **pre-disclosed escalation** — one sentence that makes §7's upgrade non-surprising

**Confirmed:** a person, a window, an address, a purpose.
**Not confirmed:** a fault, a price, a repair, a duration.

---

## 7. Post-session — preliminary scope and the upgrade path

Full ticket graph runs post-session, unchanged. Output is the **preliminary** Scope Report:
summary + band · evidence · scope tree · range · gaps.

`SAFETY_GATE` runs with full evidence and has authority to overrule pre-flight:

| Gate result | Visit becomes | Requester hears |
|---|---|---|
| Passes | Confirmed diagnostic visit stands | Nothing new — reminders only |
| **Escalates** | **Upgraded to escalation, assignment cancelled** | Proactive contact *before* the window: *"What we found suggests this needs a licensed [trade]. We've cancelled Thursday and arranged [X]."* |
| Red band / non-singleton set | Visit stands, posture set to T&M | *"This one needs eyes on it before anyone can price it — Thursday's is time-and-materials."* |

**A visit is never silently kept when the gate disagrees.** The upgrade is a first-class transition
with its own ledger event.

---

## 8. Delivery and the on-site fork

**SMS** (≤320 chars, link) + **email** (full + PDF) + **CRM record**. Target <90s p50 from session
end. Signed link, no login, 7-day expiry.

```
Hero: Diagnostic visit Thu 8-10am, 42 Wellesley #1204.
HVAC, amber. Likely condensate blockage. Model
GSX140361KA captured. Full scope: hero.ai/s/x7k2p9
```

Model number in the body is deliberate — the most useful thing a tech can know before loading the
truck. Tech also gets the **`likely_needed`** truck manifest (never `confirmed_needed` — this is
preliminary) and the ranked gaps.

**On site**, voice-first, two taps:

| Outcome | Next | Expectation |
|---|---|---|
| **Fixed on the spot** | → `COMPLETE` → invoice | **High. The happy path, not an exception** |
| **Needs parts / return** | → confirmed scope → quote → repair job | Medium |
| **Wrong trade / bigger** | → `REROUTE` with evidence attached | Low, but this is the multi-trade cascade |

**Every visit produces a `ContractorStatement`** whether or not a repair follows — labels accrue at
*visit* rate, not *completed repair* rate.

---

## 9. Commercial fork (DEC-70) — what changes

**Everything above §5 is identical.** Same assistant, same modalities, same interview, same capture,
same hazard rules. Only the terminal artifact differs.

Instead of a visit offer, the session ends with: *"I'll put this together as a quote request and send
it to [decision-maker] for approval. Once they sign off it goes to your contractors."*

Then: `RFQ_DRAFT → REQUESTER_APPROVE (INV-21) → SOLICIT → BID_RECEIVED → AWARD`.

**No RFQ leaves the building without a named decision-maker approving it (INV-21).** The reporter is
frequently not the decider — a line cook noticing a warm walk-in must not cause five vendors to
receive a solicitation. No decision-maker on file → stays in draft, human notified, **never sent to a
default.**

Full detail: PRD §4.13.

---

## 10. Drop-off analysis

Ranked by expected loss. Mitigation is a requirement at each stage.

| # | Drop point | Loss | Mitigation |
|---|---|---|---|
| 1 | **SMS link never tapped** | **Highest** | Say what happens and how long: *"Tap to show us the problem — about 3 minutes, no app or signup."* Send within 60s while intent is hot. One reminder at +10 min, then fall back to text-only |
| 2 | Consent screen bounce | High | Single screen, plain language, one button. No account, no email capture |
| 3 | Mid-session abandonment | Medium | Durability rule. Follow-up names exactly what's missing: *"Almost there — one photo of the model sticker and we're set."* |
| 4 | Offer declined / hesitated | Medium | The visit framing *is* the mitigation. Fee disclosed before confirm. Offer a callback if they stall |
| 5 | No-show | Medium | Confirmation immediately, reminders at −24h and −2h, on-my-way text |
| 6 | Escalation feels like bait-and-switch | Low but corrosive | Pre-disclosed in §6. Upgrade message leads with what was found, not the cancellation |
| 7 | **Tech skips outcome capture** | **Highest for the flywheel** | Two taps, voice-first, offline-tolerant. `COMPLETE` blocked without verdict or `unlabeled_reason` |

**Global rule: every terminal state emits a next step.** Hazard escalation ends with a callback
promise and a timeframe. Abandonment ends with a follow-up. Nothing ends in silence.

---

## 11. Data model

```sql
capture_session  (id, ticket_id, modality, mode_changes JSONB, voice_enabled,
                  turns_completed, protocol_covered[], preflight_result JSONB,
                  consent_jurisdiction, terminated_reason)
capture_turn     (id, session_id, role, text, latency_ms, capture_state JSONB)
capture_artifact (id, session_id, kind, object_key)   -- keyframe|photo|transcript_span|detection
detection        (id, artifact_id, processor_id, label, bbox, score)
live_hazard_event(id, session_id, signal, raised_at)  -- append-only

provider_capacity(provider_id, weekday, window_start, window_end, slot_count, trades[], geography)
visit            (id, ticket_id, job_id, provider_id, window_start, window_end,
                  kind, state, fee_policy, confirmed_at, read_back_at)
report_delivery  (id, scope_report_id, channel, recipient, sent_at, opened_at,
                  signed_url_expires_at)
contractor_assistant (provider_id, business_name, tone_preset, greeting, signoff,
                      policies JSONB, repo_version, drift_checked_at)
```

**Stage-first (DEC-59):** `capture_session` and `capture_artifact` persist from the raw payload
*before* identity resolution or media fetch. Enrichment columns nullable, attached later. Otherwise a
fault in that window leaves no row at all and no diagnostic can observe the loss.

Every state transition writes `job_event` (INV-11).

---

## 12. Build sequence

Ordered so each step ships something usable and de-risks the next.

| Step | Ships | Wks | Validates | Blocked on |
|---|---|---|---|---|
| **1 · Capacity + visit** (BL-35) | Capacity model, `visit`, confirm loop, reminders — **on today's text intake** | 2 | **Will a requester confirm a visit?** The whole commercial premise | BL-20 |
| **2 · Assistant identity** (BL-63) | Business name, tone preset, policies; onboarding capture | 1 | Does a company-named assistant read as that company's? | — |
| **3 · Report + delivery** (BL-19, BL-37) | Scope Report, SMS + email + signed page | 2–3 | Does a tech read it? Does it change what they load? | BL-2, BL-1 |
| **4 · On-site capture** (BL-41) | Two-tap confirm/correct, three-way fork, `ContractorStatement` | 2 | **Label velocity** | Step 3 |
| **5 · Photo-mode parity** (BL-62) | Modality selection, upload quality check, OCR on photos | 1 | Modality preference split | Step 3 |
| **6 · Pre-flight** (BL-40) | Standalone hazard + trade + client_class classifier | 1 | Escalation precision | `safety/hazards.py` |
| **7 · Hazard classifier + monitors** (BL-30, BL-45) | INV-15 interrupt, red team, failure-rate alerting | 1–2 | **Gates everything below.** Life safety | Step 6 |
| **8 · Nameplate identity** (BL-28) | Detector → OCR → equipment → warranty → corpus filter | 2 | Retrieval lift | BL-27 |
| **9 · Voice + video session** (BL-36) | Synchronised session, turn policy, `CaptureState`, processor bus | 4 | Completion rate under 5 min | Steps 6–8, DEC-33/46 residency |

**Steps 1–4 are ~7 weeks and close the entire commercial loop** — visit confirmed, report delivered,
outcome captured, label written — with no video, no voice, no residency blocker, and nothing new on
the pilot box. If that loop doesn't hold, the session work changes shape and you learned it cheaply.

**Steps 6–7 are hard prerequisites for step 9.** A live session that confirms a real appointment does
safety-critical classification in real time. Do not invert this.

**Before step 9, run a wizard-of-oz video call** — you on the other end, manual script, real
requester. Completion rate under five minutes is the gate. Ask afterwards which business they thought
they were dealing with; that validates or kills DEC-77.

---

## 13. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Assistant implies a repair is booked** | **Critical** | INV-16 + fixed language, tested like code (BL-39). "Take a look", never "fix it" |
| **Hazard mid-session while filming** | **Critical** | INV-15 pre-empts all turn policy; BL-30 red team gates the feature |
| **Photo mode under-detects hazards** | **Critical** | DEC-76: escalate on weaker evidence. Both modes red-teamed separately |
| Pre-flight clears what the gate later escalates | High | Asymmetry rule + first-class upgrade path, pre-disclosed in §6 |
| Diagnostic fee surprise at the door | High | Contractor-configured, disclosed **before** confirmation, restated in SMS |
| Tech skips outcome capture | **High (flywheel)** | Two taps, offline-tolerant; `COMPLETE` blocked without verdict |
| Visit confirmed, no provider can take it | Medium | Capacity authoritative; `MATCH` before `ASSIGN_VISIT`; overbook detection |
| Requester won't complete a video session | **Unvalidated** | Wizard-of-oz before step 9. Steps 1–5 don't depend on it |
| Preliminary report wrong often enough to erode trust | Medium | Band is calibrated (INV-4); gaps declared; *preliminary* stated on the artifact |
