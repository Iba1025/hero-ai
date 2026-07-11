import type { Me, OutcomeRequest, OutcomeResponse, TicketDetail, TicketSummary } from "./types";

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
  fileOutcome: (body: OutcomeRequest) =>
    request<OutcomeResponse>("/outcomes", { method: "POST", body: JSON.stringify(body) }),
};
