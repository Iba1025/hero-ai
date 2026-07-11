import { useEffect, useState } from "react";
import { api } from "../api";
import { navigate } from "../App";
import type { TicketSummary } from "../types";

function Badges({ t }: { t: TicketSummary }) {
  return (
    <span className="badges" style={{ marginBottom: 0 }}>
      <span className={`badge status-${t.status}`}>{t.status}</span>
      {t.trade && <span className="badge">{t.trade.replace("_", " ")}</span>}
      {t.urgency && <span className={`badge urgency-${t.urgency}`}>{t.urgency}</span>}
    </span>
  );
}

export function TicketList({ onAuthError }: { onAuthError: (err: unknown) => void }) {
  const [tickets, setTickets] = useState<TicketSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listTickets()
      .then(setTickets)
      .catch((err) => {
        onAuthError(err);
        setError("Could not load tickets");
      });
  }, [onAuthError]);

  if (error) return <div className="error">{error}</div>;
  if (tickets === null) return <div className="center muted">Loading tickets…</div>;
  if (tickets.length === 0) {
    return <div className="center muted">No tickets yet.</div>;
  }

  return (
    <div>
      {tickets.map((t) => (
        <button
          key={t.ticket_id}
          className="ticket-row"
          onClick={() => navigate(`/tickets/${t.ticket_id}`)}
        >
          <p className="desc">{t.description}</p>
          <div className="meta">
            <Badges t={t} /> · {new Date(t.created_at).toLocaleDateString()}
          </div>
        </button>
      ))}
    </div>
  );
}
