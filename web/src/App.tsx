import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { Ledger } from "./screens/Ledger";
import { Login } from "./screens/Login";
import { Outcome } from "./screens/Outcome";
import { TicketList } from "./screens/TicketList";
import type { Me } from "./types";

/** Minimal hash router: "#/tickets" (list) and "#/tickets/:id" (outcome). */
function useHashRoute(): string {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export function navigate(hash: string): void {
  window.location.hash = hash;
}

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [checking, setChecking] = useState(true);
  const route = useHashRoute();

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setChecking(false));
  }, []);

  const onLogout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setMe(null);
      navigate("");
    }
  }, []);

  // Any 401 mid-session (expired cookie) drops back to login.
  const onAuthError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 401) setMe(null);
  }, []);

  if (checking) {
    return <div className="center muted">Loading…</div>;
  }

  if (!me) {
    return <Login onLoggedIn={setMe} />;
  }

  const ticketMatch = /^#\/tickets\/([0-9a-f-]{36})$/.exec(route);

  return (
    <div className="shell">
      <header className="topbar">
        <h1>Hero</h1>
        <span className="who">
          {me.role} ·{" "}
          <button className="linklike" onClick={onLogout}>
            Sign out
          </button>
        </span>
      </header>
      {ticketMatch ? (
        // Same route, role-appropriate view: operators/admins get the full
        // audit-trail ledger; contractors keep the narrower outcome screen.
        me.role === "contractor" ? (
          <Outcome ticketId={ticketMatch[1]} role={me.role} onAuthError={onAuthError} />
        ) : (
          <Ledger ticketId={ticketMatch[1]} onAuthError={onAuthError} />
        )
      ) : (
        <TicketList onAuthError={onAuthError} />
      )}
    </div>
  );
}
