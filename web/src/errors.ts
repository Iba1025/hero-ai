// H5 / BL-21 — tenant-facing error copy. Rules (FRICTION.md): errors must be
// human, must state clearly whether the report went through, and must give a
// retry path. Never show a raw "Internal Server Error" to a tenant.

import { ApiError } from "./api";

/** What the tenant was trying to send — inserted into the copy. */
export type SendKind = "report" | "message" | "answer";

/**
 * Honest, human copy per failure class:
 * - 4xx: the send was rejected — it did NOT go through, retrying is safe.
 * - 5xx: our side broke AFTER receiving the request — it MAY have gone
 *   through (the rehearsal's "Internal Server Error on a successful
 *   submission"), so tell the tenant to check before resending.
 * - network: nothing reached us — it did NOT go through, retrying is safe.
 */
export function tenantErrorCopy(err: unknown, kind: SendKind): string {
  const thing = kind === "report" ? "Your report" : kind === "answer" ? "Your answer" : "Your message";
  if (err instanceof ApiError) {
    if (err.status === 429) {
      return `${thing} was NOT sent — we’re receiving a lot right now. Please wait a few minutes and send it again.`;
    }
    if (err.status === 404) {
      return `${thing} was NOT sent — this link is no longer valid. Ask your building manager for a new one.`;
    }
    if (err.status >= 500) {
      return `Something went wrong on our side. ${thing} may still have gone through — please wait a minute and refresh this page before sending it again, so it isn’t filed twice.`;
    }
    // Other 4xx: rejected before anything was created.
    return `${thing} was NOT sent — ${humanDetail(err)}. Please adjust it and try again.`;
  }
  return `${thing} was NOT sent — we couldn’t reach the server. Check your connection and try again.`;
}

function humanDetail(err: ApiError): string {
  // Server 4xx details are already written for tenants (public.py); the one
  // exception is FastAPI's default 422 phrasing ("Unprocessable Entity").
  if (err.status === 422 && err.message.toLowerCase().includes("unprocessable")) {
    return "it looks like the text was empty or too long";
  }
  return err.message.charAt(0).toLowerCase() + err.message.slice(1).replace(/\.$/, "");
}
