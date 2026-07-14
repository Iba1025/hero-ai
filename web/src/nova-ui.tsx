// Nova tenant-chat chrome (DEC-26): Hero-Diagnosis visual language.
// Inline SVG icons only — the design bundle is reference, never a dependency.

import type { ReactNode } from "react";
import type { PublicChatMessage } from "./types";

export function ArrowLeftIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M19 12H5" />
      <path d="M12 19l-7-7 7-7" />
    </svg>
  );
}

export function CameraIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" />
      <circle cx="12" cy="13" r="3" />
    </svg>
  );
}

export function SendIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 2L11 13" />
      <path d="M22 2l-7 20-4-9-9-4 20-7z" />
    </svg>
  );
}

/** App bar: history-back (hidden when this tab has no history — DEC-26),
    centered title, right side intentionally empty (kebab/speaker omitted:
    voice is deferred by DEC-25). */
export function NovaHeader({ title = "Hero Assistant" }: { title?: string }) {
  const canGoBack = window.history.length > 1;
  return (
    <div className="nova-header">
      {canGoBack ? (
        <button className="icon-btn" aria-label="Back" onClick={() => window.history.back()}>
          <ArrowLeftIcon />
        </button>
      ) : (
        <div className="icon-spacer" />
      )}
      <h1>{title}</h1>
      <div className="icon-spacer" />
    </div>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** One transcript entry. Fixed safety copy stays a full-width banner
    (escalation warn, redirect/capped plain) — INV-1/DEC-24 states survive
    the retheme. Everything else is an avatar-and-bubble row. */
export function NovaBubble({ message }: { message: PublicChatMessage }) {
  if (message.kind === "escalation") return <div className="banner warn">{message.body}</div>;
  if (message.kind === "redirect" || message.kind === "capped") {
    return <div className="banner">{message.body}</div>;
  }
  const isNova = message.sender === "nova";
  return (
    <div className={`nova-row ${message.sender}`}>
      {isNova && <div className="nova-avatar" />}
      <div className="msg-col">
        <div className={`bubble ${message.sender}${message.kind === "photo" ? " photo" : ""}`}>
          {message.body}
        </div>
        {message.created_at && <span className="msg-ts">{formatTime(message.created_at)}</span>}
      </div>
    </div>
  );
}

/** A static Nova bubble for client-side fixed copy (no timestamp). */
export function NovaStaticBubble({ children }: { children: ReactNode }) {
  return (
    <div className="nova-row nova">
      <div className="nova-avatar" />
      <div className="msg-col">
        <div className="bubble nova">{children}</div>
      </div>
    </div>
  );
}
