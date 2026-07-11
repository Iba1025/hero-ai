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
