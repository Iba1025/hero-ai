import type {
  LedgerResponse,
  Me,
  OutcomeRequest,
  OutcomeResponse,
  PublicChatReply,
  PublicChatStart,
  PublicConversation,
  PublicIntakeResponse,
  PublicPhoto,
  PublicPresignResponse,
  PublicStatus,
  TicketDetail,
  TicketSummary,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    credentials: "same-origin", // hero_session cookie is first-party via the Vite proxy
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  me: () => request<Me>("/auth/me"),
  login: (email: string, password: string) =>
    request<Me>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<{ status: string }>("/auth/logout", { method: "POST" }),
  listTickets: () => request<TicketSummary[]>("/tickets"),
  getTicket: (id: string) => request<TicketDetail>(`/tickets/${id}`),
  getLedger: (id: string) => request<LedgerResponse>(`/tickets/${id}/ledger`),
  // Timeout so a wedged server can never leave the UI at "Filing…" forever —
  // the pilot-rehearsal outcome loss looked exactly like that (FRICTION.md).
  fileOutcome: (body: OutcomeRequest) =>
    request<OutcomeResponse>("/outcomes", {
      method: "POST",
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(20_000),
    }),

  // ---- public tenant intake (P4-4): no session, the slug is the credential ----
  publicBuilding: (slug: string) =>
    request<{ name: string }>(`/public/buildings/${encodeURIComponent(slug)}`),
  publicPresign: (slug: string, body: { filename: string; content_type: string; size_bytes: number }) =>
    request<PublicPresignResponse>(`/public/buildings/${encodeURIComponent(slug)}/presign`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  publicIntake: (slug: string, body: { description: string; contact: string; photos: PublicPhoto[] }) =>
    request<PublicIntakeResponse>(`/public/buildings/${encodeURIComponent(slug)}/tickets`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  publicStatus: (statusSlug: string) =>
    request<PublicStatus>(`/public/status/${encodeURIComponent(statusSlug)}`),
  publicAnswer: (statusSlug: string, answer: string) =>
    request<PublicStatus>(`/public/status/${encodeURIComponent(statusSlug)}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),

  // ---- Nova chat (Phase 5 STEP 4, DEC-23/24) ----
  publicChatStart: (slug: string, body: { message: string; contact: string; photos: PublicPhoto[] }) =>
    request<PublicChatStart>(`/public/buildings/${encodeURIComponent(slug)}/conversations`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  publicConversation: (statusSlug: string) =>
    request<PublicConversation>(`/public/status/${encodeURIComponent(statusSlug)}/messages`),
  publicChatSend: (statusSlug: string, message: string) =>
    request<PublicChatReply>(`/public/status/${encodeURIComponent(statusSlug)}/messages`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
};

/** Direct-to-R2 PUT (INV-3): media bytes never touch our server. */
export async function uploadToPresigned(url: string, file: File): Promise<void> {
  const resp = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": file.type },
    body: file,
  });
  if (!resp.ok) throw new ApiError(resp.status, "Photo upload failed");
}
