import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { navigate } from "../App";
import type { LedgerEntry, LedgerResponse } from "../types";

/* The ledger renders only persisted facts. Every accessor below is
   defensive: a missing field renders as absent, never invented. */

function str(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" ? v : null;
}

function list(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter((x): x is Record<string, unknown> => !!x && typeof x === "object") : [];
}

const STATE_LABELS: Record<string, string> = {
  intake: "Intake",
  triage: "Triage",
  retrieve: "Retrieve",
  clarify_pending: "Clarify — question sent",
  clarify_answered: "Clarify — answered",
  diagnose: "Diagnose",
  verify: "Verify",
  safety_gate: "Safety gate",
  procure: "Procure",
  outcome: "Contractor outcome",
};

function Cite({ c }: { c: Record<string, unknown> }) {
  const page = num(c.page);
  const stage = str(c.retrieval_stage);
  return (
    <span className="cite">
      {str(c.doc_id) ?? "?"} p.{page !== null ? page + 1 : "?"}
      {stage ? ` · ${stage}` : ""}
    </span>
  );
}

function EntryBody({ entry, isLast }: { entry: LedgerEntry; isLast: boolean }) {
  const d = entry.data;
  switch (entry.state) {
    case "intake":
      return <p className="entry-text">{str(d.description)}</p>;

    case "triage":
      return (
        <div className="badges">
          {str(d.trade) && <span className="badge">{str(d.trade)!.replace("_", " ")}</span>}
          {str(d.urgency) && (
            <span className={`badge urgency-${str(d.urgency)}`}>{str(d.urgency)}</span>
          )}
          {str(d.complexity) && <span className="badge">{str(d.complexity)}</span>}
          {str(d.path) && <span className="badge">{str(d.path)} path</span>}
        </div>
      );

    case "retrieve":
      return (
        <div>
          {list(d.citations).map((c, i) => (
            <Cite key={i} c={c} />
          ))}
        </div>
      );

    case "clarify_pending":
      return (
        <div>
          <p className="entry-text">“{str(d.question)}”</p>
          {isLast && <span className="badge status-clarifying">awaiting tenant answer</span>}
        </div>
      );

    case "clarify_answered":
      return (
        <div>
          <p className="entry-text muted">“{str(d.question)}”</p>
          <p className="entry-text">↳ {str(d.answer)}</p>
        </div>
      );

    case "diagnose":
      return (
        <div>
          {list(d.hypotheses).map((h, i) => (
            <div key={i} className="hypothesis">
              <p className="entry-text">
                <strong>{str(h.fault)}</strong>
                {num(h.calibrated_confidence) !== null && (
                  <span className="mono soft">
                    {" "}
                    · calibrated {(num(h.calibrated_confidence)! * 100).toFixed(0)}%
                  </span>
                )}
              </p>
              {(Array.isArray(h.reasoning) ? h.reasoning : [])
                .filter((r): r is string => typeof r === "string")
                .map((r, j) => (
                  <p key={j} className="entry-text muted">
                    – {r}
                  </p>
                ))}
            </div>
          ))}
        </div>
      );

    case "verify":
      return (
        <div>
          <p className="entry-text">
            {d.verify_pass === true ? "Grounding check passed" : "Grounding check FAILED"}
            {str(d.fault) && (
              <span className="muted"> — primary hypothesis persisted: {str(d.fault)}</span>
            )}
          </p>
          {list(d.claims).map((c, i) => (
            <div key={i} className="claim">
              <span className={`mark ${c.grounded === true ? "grounded" : "ungrounded"}`}>
                {c.grounded === true ? "✓" : "✕"}
              </span>
              <span>
                {str(c.text)} <span className="mono soft">[{str(c.claim_type) ?? "?"}]</span>
                <span style={{ display: "block" }}>
                  {list(c.citations).map((cc, j) => (
                    <Cite key={j} c={cc} />
                  ))}
                </span>
              </span>
            </div>
          ))}
        </div>
      );

    case "safety_gate":
      return d.escalated === true ? (
        <div className="banner escalated">
          ⚠ ESCALATED{str(d.escalation_reason) ? ` — ${str(d.escalation_reason)}` : ""}
        </div>
      ) : (
        <p className="entry-text">Passed — no escalation.</p>
      );

    case "procure":
      return (
        <p className="entry-text mono">
          {str(d.work_order_id) && <>WO {str(d.work_order_id)}</>}
          {str(d.sku) && <> · SKU {str(d.sku)}</>}
        </p>
      );

    case "outcome":
      return (
        <div>
          {str(d.verdict) && (
            <span className={`badge verdict-${str(d.verdict)}`}>
              {str(d.verdict)!.replace("_", " ")}
            </span>
          )}
          {str(d.unlabeled_reason) && (
            <p className="entry-text muted">Not assessed: {str(d.unlabeled_reason)}</p>
          )}
          {str(d.actual_fault) && (
            <p className="entry-text">Actual fault: {str(d.actual_fault)}</p>
          )}
          {str(d.actual_part_sku) && (
            <p className="entry-text mono">Part used: {str(d.actual_part_sku)}</p>
          )}
          {str(d.free_text) && <p className="entry-text">“{str(d.free_text)}”</p>}
          {str(d.contractor_id) && (
            <p className="entry-text mono soft">contractor {str(d.contractor_id)}</p>
          )}
        </div>
      );

    default:
      // Unknown state name: show it honestly rather than hiding it.
      return <p className="entry-text mono soft">{JSON.stringify(d)}</p>;
  }
}

export function Ledger({
  ticketId,
  onAuthError,
}: {
  ticketId: string;
  onAuthError: (err: unknown) => void;
}) {
  const [ledger, setLedger] = useState<LedgerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getLedger(ticketId)
      .then(setLedger)
      .catch((err) => {
        onAuthError(err);
        setError(err instanceof ApiError ? err.message : "Could not load ledger");
      });
  }, [ticketId, onAuthError]);

  if (error) return <div className="error">{error}</div>;
  if (!ledger) return <div className="center muted">Loading ledger…</div>;

  return (
    <div>
      <button className="back-btn" onClick={() => navigate("")}>
        ‹ All tickets
      </button>

      <div className="card">
        <div className="badges">
          <span className={`badge status-${ledger.status}`}>{ledger.status}</span>
          {ledger.trade && <span className="badge">{ledger.trade.replace("_", " ")}</span>}
          {ledger.urgency && (
            <span className={`badge urgency-${ledger.urgency}`}>{ledger.urgency}</span>
          )}
          {ledger.complexity && <span className="badge">{ledger.complexity}</span>}
        </div>
        <p style={{ margin: "4px 0 8px" }}>{ledger.description}</p>
        <p className="mono soft" style={{ margin: 0, fontSize: 12 }}>
          ticket {ledger.ticket_id} · building {ledger.building_id}
        </p>
      </div>

      <div className="ledger">
        {ledger.entries.map((entry, i) => (
          <div key={i} className={`ledger-entry ${entry.state}`}>
            <div className="entry-head">
              <span className="entry-state">{STATE_LABELS[entry.state] ?? entry.state}</span>
              <span className="mono soft entry-ts">
                {new Date(entry.ts).toLocaleString(undefined, {
                  month: "short",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
            </div>
            <EntryBody entry={entry} isLast={i === ledger.entries.length - 1} />
          </div>
        ))}
      </div>
    </div>
  );
}
