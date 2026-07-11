import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { navigate } from "../App";
import type { Claim, Hypothesis, TicketDetail, Verdict } from "../types";

const VERDICTS: { value: Verdict; label: string; icon: string }[] = [
  { value: "confirmed", label: "Confirmed", icon: "✓" },
  { value: "partially_correct", label: "Partially right", icon: "±" },
  { value: "wrong", label: "Wrong", icon: "✕" },
];

/** Same rule as the API's persist step: highest calibrated confidence wins. */
function primaryHypothesis(hypotheses: Hypothesis[]): Hypothesis | null {
  if (hypotheses.length === 0) return null;
  return hypotheses.reduce((best, h) =>
    (h.calibrated_confidence ?? 0) > (best.calibrated_confidence ?? 0) ? h : best,
  );
}

function ClaimRow({ claim }: { claim: Claim }) {
  const cites = claim.supporting_evidence ?? [];
  return (
    <div className="claim">
      <span
        className={`mark ${claim.grounded ? "grounded" : "ungrounded"}`}
        title={claim.grounded ? "Grounded in the manual" : "Not grounded in the manual"}
      >
        {claim.grounded ? "✓" : "–"}
      </span>
      <span>
        {claim.text}
        {cites.length > 0 && (
          <span style={{ display: "block" }}>
            {cites.map((c, i) => (
              <span key={i} className="cite">
                {c.doc_id} p.{c.page + 1}
              </span>
            ))}
          </span>
        )}
      </span>
    </div>
  );
}

export function Outcome({
  ticketId,
  role,
  onAuthError,
}: {
  ticketId: string;
  role: string;
  onAuthError: (err: unknown) => void;
}) {
  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [cantAssess, setCantAssess] = useState(false);
  const [actualFault, setActualFault] = useState("");
  const [partSku, setPartSku] = useState("");
  const [freeText, setFreeText] = useState("");
  const [unlabeledReason, setUnlabeledReason] = useState("");

  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [filed, setFiled] = useState(false);

  useEffect(() => {
    api
      .getTicket(ticketId)
      .then(setTicket)
      .catch((err) => {
        onAuthError(err);
        setLoadError(err instanceof ApiError ? err.message : "Could not load ticket");
      });
  }, [ticketId, onAuthError]);

  const primary = useMemo(() => primaryHypothesis(ticket?.hypotheses ?? []), [ticket]);
  const needsFault = verdict === "partially_correct" || verdict === "wrong";
  const canFileOutcome = role === "contractor" || role === "admin";
  const alreadyResolved = ticket?.status === "resolved";

  const ready = cantAssess
    ? unlabeledReason.trim().length > 0
    : verdict !== null && (!needsFault || actualFault.trim().length > 0);

  async function submit() {
    setBusy(true);
    setSubmitError(null);
    try {
      await api.fileOutcome({
        ticket_id: ticketId,
        ...(cantAssess
          ? { unlabeled_reason: unlabeledReason.trim() }
          : {
              verdict: verdict!,
              ...(needsFault ? { actual_fault: actualFault.trim() } : {}),
              ...(needsFault && partSku.trim() ? { actual_part_sku: partSku.trim() } : {}),
              ...(freeText.trim() ? { free_text: freeText.trim() } : {}),
            }),
      });
      setFiled(true);
    } catch (err) {
      onAuthError(err);
      setSubmitError(err instanceof ApiError ? err.message : "Could not file outcome");
    } finally {
      setBusy(false);
    }
  }

  if (loadError) return <div className="error">{loadError}</div>;
  if (!ticket) return <div className="center muted">Loading ticket…</div>;

  if (filed) {
    return (
      <div className="center">
        <div className="success-mark">✓</div>
        <h2 style={{ margin: "0 0 4px" }}>Outcome filed</h2>
        <p className="muted">Ticket marked resolved. Thanks — this trains the system.</p>
        <button className="primary-btn" onClick={() => navigate("")}>
          Back to tickets
        </button>
      </div>
    );
  }

  return (
    <div>
      <button className="back-btn" onClick={() => navigate("")}>
        ‹ All tickets
      </button>

      <div className="card">
        <div className="badges">
          <span className={`badge status-${ticket.status}`}>{ticket.status}</span>
          {ticket.trade && <span className="badge">{ticket.trade.replace("_", " ")}</span>}
          {ticket.urgency && (
            <span className={`badge urgency-${ticket.urgency}`}>{ticket.urgency}</span>
          )}
        </div>
        {ticket.sku && (
          <p className="muted" style={{ margin: 0 }}>
            Suggested part: <strong>{ticket.sku}</strong>
          </p>
        )}
      </div>

      {ticket.escalated && (
        <div className="banner warn">
          Escalated to a human{ticket.escalation_reason ? `: ${ticket.escalation_reason}` : ""}.
        </div>
      )}

      <div className="card">
        <h2>AI diagnosis</h2>
        {primary ? (
          <>
            <p className="fault">{primary.fault}</p>
            {(primary.claims ?? []).map((c, i) => (
              <ClaimRow key={i} claim={c} />
            ))}
          </>
        ) : (
          <p className="muted" style={{ margin: 0 }}>
            No diagnosis yet
            {ticket.pending_question ? " — waiting on a clarification from the tenant." : "."}
          </p>
        )}
      </div>

      {!canFileOutcome ? (
        <p className="muted">Outcomes are filed by the contractor on site.</p>
      ) : alreadyResolved ? (
        <p className="muted">An outcome has already been filed for this ticket.</p>
      ) : primary ? (
        <div className="card">
          <h2>Was the diagnosis right?</h2>
          {!cantAssess && (
            <div className="verdicts">
              {VERDICTS.map((v) => (
                <button
                  key={v.value}
                  className={`verdict-btn ${v.value} ${verdict === v.value ? "selected" : ""}`}
                  onClick={() => setVerdict(v.value)}
                >
                  <span>{v.icon}</span> {v.label}
                </button>
              ))}
            </div>
          )}

          {needsFault && !cantAssess && (
            <>
              <label className="field">
                What was the actual fault?
                <textarea
                  value={actualFault}
                  onChange={(e) => setActualFault(e.target.value)}
                  placeholder="e.g. Failing run capacitor on the compressor"
                />
              </label>
              <label className="field">
                Part used (optional)
                <input
                  type="text"
                  value={partSku}
                  onChange={(e) => setPartSku(e.target.value)}
                  placeholder="Part SKU"
                />
              </label>
              {ticket.sku && (
                <div className="chips">
                  <button
                    className={`chip ${partSku === ticket.sku ? "selected" : ""}`}
                    onClick={() => setPartSku(partSku === ticket.sku ? "" : ticket.sku!)}
                  >
                    {ticket.sku}
                  </button>
                </div>
              )}
            </>
          )}

          {!cantAssess && verdict && (
            <label className="field">
              Notes (optional)
              <textarea
                value={freeText}
                onChange={(e) => setFreeText(e.target.value)}
                placeholder="Anything else worth recording"
              />
            </label>
          )}

          {cantAssess && (
            <label className="field">
              Why can’t this be assessed?
              <textarea
                value={unlabeledReason}
                onChange={(e) => setUnlabeledReason(e.target.value)}
                placeholder="e.g. Tenant not home, could not access the unit"
                autoFocus
              />
            </label>
          )}

          {submitError && <div className="error">{submitError}</div>}

          <button className="primary-btn" disabled={!ready || busy} onClick={submit}>
            {busy ? "Filing…" : "File outcome"}
          </button>

          <div style={{ textAlign: "center", marginTop: 8 }}>
            <button
              className="linklike"
              onClick={() => {
                setCantAssess(!cantAssess);
                setVerdict(null);
              }}
            >
              {cantAssess ? "Back to verdicts" : "Can’t assess this one"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
