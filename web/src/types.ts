// Mirrors the FastAPI response models — keep in sync with src/hero/api/routers/.

export interface Me {
  user_id: string;
  org_id: string;
  role: "operator" | "contractor" | "admin";
}

export interface TicketSummary {
  ticket_id: string;
  description: string;
  status: string;
  trade: string | null;
  urgency: string | null;
  complexity: string | null;
  created_at: string;
}

export interface EvidenceChunk {
  doc_id: string;
  page: number;
}

export interface Claim {
  text: string;
  claim_type?: string;
  grounded?: boolean;
  supporting_evidence?: EvidenceChunk[];
}

export interface Hypothesis {
  fault: string;
  calibrated_confidence?: number | null;
  claims?: Claim[];
}

export interface TicketDetail {
  ticket_id: string;
  status: string;
  trade: string | null;
  urgency: string | null;
  escalated: boolean;
  escalation_reason: string | null;
  verify_pass: boolean | null;
  hypotheses: Hypothesis[];
  work_order_id: string | null;
  sku: string | null;
  pending_question: string | null;
}

export interface LedgerEntry {
  state: string;
  ts: string;
  run_id: string | null;
  // Payload shape varies by state — rendered defensively, absent means absent.
  data: Record<string, unknown>;
}

export interface LedgerResponse {
  ticket_id: string;
  building_id: string;
  description: string;
  status: string;
  trade: string | null;
  urgency: string | null;
  complexity: string | null;
  created_at: string;
  entries: LedgerEntry[];
}

// ---- public tenant intake (P4-4) — no auth, slug is the credential ----

export interface PublicPresignResponse {
  upload_url: string;
  object_key: string;
}

export interface PublicPhoto {
  object_key: string;
  content_type: string;
  sha256?: string | null;
}

export interface PublicIntakeResponse {
  status_slug: string;
  status_path: string;
}

export interface PublicStatus {
  // Plain-language phrase from the server, e.g. "received", "question for you".
  state: string;
  question: string | null;
  description: string;
  created_at: string;
  // True while the pipeline works in the background (BL-17) — the UI polls.
  working: boolean;
}

// ---- Nova chat (Phase 5 STEP 4, DEC-23/24) ----

export interface PublicChatMessage {
  sender: "tenant" | "nova";
  // Render hint only: escalation/redirect are banners, the rest are bubbles.
  kind: string;
  body: string;
  created_at: string;
}

export interface PublicChatStart {
  // Null when the opener was redirected (DEC-24): nothing was created.
  status_slug: string | null;
  status_path: string | null;
  reply: PublicChatMessage;
}

export interface PublicChatReply {
  reply: PublicChatMessage;
  working: boolean;
}

export interface PublicConversation {
  state: string;
  working: boolean;
  messages: PublicChatMessage[];
}

export type Verdict = "confirmed" | "partially_correct" | "wrong";

export interface OutcomeRequest {
  ticket_id: string;
  verdict?: Verdict;
  actual_fault?: string;
  actual_part_sku?: string;
  free_text?: string;
  unlabeled_reason?: string;
}

export interface OutcomeResponse {
  id: string;
  ticket_id: string;
  status: string;
}
