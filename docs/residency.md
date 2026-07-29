# Data residency register — INV-2

> One row per service that touches ticket content outside our own boxes.
> Required by INV-2 as amended (DEC-33: voice/transcripts/telephony metadata are ticket
> content; DEC-46: video frames and detections are ticket content) and by DEC-29/81.
> **Update this table in the same PR as any adapter, vendor, or region change.**
> A procurement reviewer must find the exceptions here, not discover them.

## In use (pilot, lean mode)

| Service | Purpose | Region | Data crossing | Retention | Mitigation / decision | Reviewed |
|---|---|---|---|---|---|---|
| **Cloudflare Workers AI — `@cf/baai/bge-m3`** | Ingestion + query embedding (lean mode) | **Global — NO Canadian residency commitment** | Manual page text, query text | Cloudflare states inputs/outputs are not used to train models | ⚠️ **RECORDED INV-2 EXCEPTION, not compliance** — founder-approved 2026-07-30, recorded as **DEC-87**. Pairs with DEC-28 (R2) in any procurement review. Migration target: Bedrock ca-central-1 (rows below). Trigger mirrors DEC-28: BEFORE any procurement/compliance review and BEFORE the first paying customer | 2026-07-30 |
| **Cloudflare Workers AI — `@cf/baai/bge-reranker-base`** | Retrieval reranking (lean mode) | **Global — NO Canadian residency commitment** | Query + candidate chunk text | As above | ⚠️ Same recorded exception as above | 2026-07-30 |

## Migration target (INV-2-clean, adapters built and unused — no AWS credentials yet)

| Service | Purpose | Region | Data crossing | Retention | Mitigation / decision | Reviewed |
|---|---|---|---|---|---|---|
| AWS Bedrock — Cohere Embed Multilingual v3 (`cohere.embed-multilingual-v3`) | Ingestion + query embedding | **ca-central-1** (AWS lists In-Region ✓) | Manual page text, query text | Bedrock does not retain prompts for model training (AWS commitment) | DEC-29. In-region → **no INV-2 gap**. Embed v4 rejected: Global cross-region only at ca-central-1 | 2026-07-29 |
| AWS Bedrock — Cohere Rerank 3.5 (`cohere.rerank-v3-5:0`) | Retrieval reranking | **ca-central-1** (AWS lists single-region supported *in* ca-central-1) | Query + candidate chunk text | As above | DEC-29. In-region → **no INV-2 gap** | 2026-07-29 |
| Cloudflare R2 | Tenant-submitted media (photos) | **NA location hint — no Canadian jurisdiction guarantee** | Photo bytes (pointers only in Postgres, INV-3) | Until deleted by us | **DEC-28 recorded INV-2 exception — top open risk.** Hard migration trigger: BEFORE any procurement/compliance review and BEFORE the first paying customer. Swap is presign-config + object copy only (INV-3) | 2026-07-29 |

## Recorded postures for services NOT yet in use (do not onboard without updating this table)

| Service | Purpose | Region | Data crossing | Retention | Mitigation / decision | Reviewed |
|---|---|---|---|---|---|---|
| Twilio | SMS / voice-call **transit only** | US1 (no CA region offered) | Message bodies, call audio in transit | **Body redaction ON, recording OFF at account level; MMS fetched to R2 immediately, Twilio copy deleted** | **DEC-81: recorded INV-2 exception, not compliance.** Transit, never storage. BL-71 is the prerequisite for any SMS/voice channel | 2026-07-29 (posture only) |
| ElevenLabs | TTS **only** (agent speech out) | EU workspace (closest offered; not CA) | Templated outbound text — **no requester PII interpolated, enforced by tests (BL-72)** | Enterprise **Zero Retention Mode** | **DEC-81 exception.** No voice cloning ever (DEC-79/INV-22a). Fallback: self-hosted neutral TTS (Piper/Coqui class) | 2026-07-29 (posture only) |
| ASR (speech → text) | Requester speech transcription | **Self-hosted, in-region** — never a US/EU API | Requester's actual words (unambiguously ticket content) | n/a (ours) | DEC-81/BL-72: the high-exposure direction is eliminated outright, not mitigated | 2026-07-29 (posture only) |

## Everything else

Postgres, Qdrant, and the API run on the pilot VM (DigitalOcean **TOR1**, DEC-27).
Langfuse is deferred (DEC-30) — no trace content leaves the box because tracing no-ops
when `LANGFUSE_*` is unset (`src/hero/observability/tracing.py`).

## Startup guard status

`region_guard(settings)` (`src/hero/config.py`, called from API startup) already asserts
Canadian-region config for the stores and Bedrock endpoints. Extending it to assert
**config matches this table row-for-row** is Class B work (it can refuse to boot) and is
deliberately deferred until after the deploy gate — see WORK_ORDER_v8.2.md Amendments
(2026-07-29), item 1.
