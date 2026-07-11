import { useEffect, useState } from "react";
import { api } from "../api";
import { navigate } from "../App";
import type { TicketSummary } from "../types";

const STATUS_FILTERS = ["all", "open", "clarifying", "diagnosed", "escalated", "resolved"];

function Badges({ t }: { t: TicketSummary }) {
  return (
    <span className="badges" style={{ marginBottom: 0 }}>
      <span className={`badge status-${t.status}`}>
        {t.status === "escalated" ? "⚠ escalated" : t.status}
      </span>
      {t.trade && <span className="badge">{t.trade.replace("_", " ")}</span>}
      {t.urgency && <span className={`badge urgency-${t.urgency}`}>{t.urgency}</span>}
      {t.complexity && <span className="badge">{t.complexity}</span>}
    </span>
  );
}

export function TicketList({ onAuthError }: { onAuthError: (err: unknown) => void }) {
  const [tickets, setTickets] = useState<TicketSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");

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

  const visible = filter === "all" ? tickets : tickets.filter((t) => t.status === filter);

  return (
    <div>
      <div className="chips" style={{ marginBottom: 12 }}>
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            className={`chip ${filter === s ? "selected" : ""}`}
            onClick={() => setFilter(s)}
          >
            {s}
          </button>
        ))}
      </div>
      {visible.length === 0 ? (
        <div className="center muted">
          {tickets.length === 0 ? "No tickets yet." : `No ${filter} tickets.`}
        </div>
      ) : (
        visible.map((t) => (
          <button
            key={t.ticket_id}
            className="ticket-row"
            onClick={() => navigate(`/tickets/${t.ticket_id}`)}
          >
            <p className="desc">{t.description}</p>
            <div className="meta">
              <Badges t={t} /> ·{" "}
              <span className="mono">
                {new Date(t.created_at).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </div>
          </button>
        ))
      )}
    </div>
  );
}
