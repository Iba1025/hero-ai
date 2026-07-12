import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { PublicStatus } from "../types";

// Server sends the plain-language phrase; this adds one friendly sentence.
const EXPLAIN: Record<string, string> = {
  received: "We’ve received your report.",
  "question for you": "We need one detail from you to keep going.",
  "looking into it": "Someone is looking into it.",
  "being handled": "A repair is being arranged.",
  resolved: "This issue has been resolved.",
};

export function StatusPage({ slug }: { slug: string }) {
  const [status, setStatus] = useState<PublicStatus | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .publicStatus(slug)
      .then(setStatus)
      .catch(() => setNotFound(true));
  }, [slug]);

  useEffect(load, [load]);

  const sendAnswer = async () => {
    setSending(true);
    setError(null);
    try {
      const next = await api.publicAnswer(slug, answer.trim());
      setStatus(next);
      setAnswer("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send your answer");
    } finally {
      setSending(false);
    }
  };

  if (notFound) {
    return (
      <div className="shell">
        <div className="center muted">This status link isn’t valid.</div>
      </div>
    );
  }
  if (!status) {
    return (
      <div className="shell">
        <div className="center muted">Loading…</div>
      </div>
    );
  }

  return (
    <div className="shell">
      <div className="login-wrap">
        <div className="brand">Your report</div>
        <div className="card">
          <h2>Status</h2>
          <p className="status-phrase">{status.state}</p>
          <p className="muted" style={{ margin: 0 }}>
            {EXPLAIN[status.state] ?? ""}
          </p>
        </div>

        <div className="card">
          <h2>You reported</h2>
          <p style={{ margin: 0 }}>{status.description}</p>
        </div>

        {status.question && (
          <div className="card">
            <h2>Question for you</h2>
            <p style={{ margin: "0 0 8px" }}>“{status.question}”</p>
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Type your answer"
              maxLength={4000}
            />
            {error && <div className="error">{error}</div>}
            <button
              className="primary-btn"
              disabled={answer.trim().length === 0 || sending}
              onClick={sendAnswer}
            >
              {sending ? "Sending…" : "Send answer"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
