import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { tenantErrorCopy } from "../errors";
import type { PublicChatMessage, PublicConversation, PublicStatus } from "../types";

// Server sends the plain-language phrase; this adds one friendly sentence.
const EXPLAIN: Record<string, string> = {
  received: "We’ve received your report.",
  "question for you": "We need one detail from you to keep going.",
  "looking into it": "Someone is looking into it.",
  "being handled": "A repair is being arranged.",
  resolved: "This issue has been resolved.",
};

// Honest progress copy (FRICTION H1): the first run pays retrieval + checks.
const WORKING_COPY = "Checking the equipment’s manuals — this can take about half a minute.";

const POLL_MS = 3000;

export function StatusPage({ slug }: { slug: string }) {
  const [status, setStatus] = useState<PublicStatus | null>(null);
  const [conversation, setConversation] = useState<PublicConversation | null>(null);
  const [notFound, setNotFound] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [st, convo] = await Promise.all([api.publicStatus(slug), api.publicConversation(slug)]);
      setStatus(st);
      setConversation(convo);
    } catch {
      setNotFound(true);
    }
  }, [slug]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll while the pipeline works — the diagnosis/question arrives on its own.
  const working = (status?.working ?? false) || (conversation?.working ?? false);
  useEffect(() => {
    if (!working || notFound) return;
    const id = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(id);
  }, [working, notFound, refresh]);

  if (notFound) {
    return (
      <div className="shell">
        <div className="center muted">This status link isn’t valid.</div>
      </div>
    );
  }
  if (!status || !conversation) {
    return (
      <div className="shell">
        <div className="center muted">Loading…</div>
      </div>
    );
  }

  // Chat-intake tickets (DEC-23) render the live conversation; form tickets
  // keep the status card + one-shot answer box.
  if (conversation.messages.length > 0) {
    return <ConversationView slug={slug} conversation={conversation} onSent={refresh} />;
  }
  return <FormStatusView slug={slug} status={status} onAnswered={setStatus} />;
}

// ---- form tickets (P4-4) ----

function FormStatusView({
  slug,
  status,
  onAnswered,
}: {
  slug: string;
  status: PublicStatus;
  onAnswered: (next: PublicStatus) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sendAnswer = async () => {
    setSending(true);
    setError(null);
    try {
      const next = await api.publicAnswer(slug, answer.trim());
      onAnswered(next);
      setAnswer("");
    } catch (err) {
      setError(tenantErrorCopy(err, "answer"));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="shell">
      <div className="login-wrap">
        <div className="brand">Your report</div>
        <div className="card">
          <h2>Status</h2>
          <p className="status-phrase">{status.state}</p>
          <p className="muted" style={{ margin: 0 }}>
            {status.working ? WORKING_COPY : (EXPLAIN[status.state] ?? "")}
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

// ---- chat tickets (DEC-23/24) ----

function ConversationView({
  slug,
  conversation,
  onSent,
}: {
  slug: string;
  conversation: PublicConversation;
  onSent: () => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [conversation.messages.length]);

  const send = async () => {
    setSending(true);
    setError(null);
    try {
      await api.publicChatSend(slug, draft.trim());
      setDraft("");
      await onSent(); // re-fetch the transcript — the server owns the truth
    } catch (err) {
      setError(tenantErrorCopy(err, "message"));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="shell">
      <div className="login-wrap">
        <div className="brand">Your report</div>
        <p className="status-phrase" style={{ margin: "0 0 10px" }}>
          {conversation.state}
        </p>

        <div className="chat-log">
          {conversation.messages.map((m, i) => (
            <ChatBubble key={i} message={m} />
          ))}
          {conversation.working && <div className="muted working-note">{WORKING_COPY}</div>}
          <div ref={bottom} />
        </div>

        {error && <div className="error">{error}</div>}

        <div className="composer">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Write a message"
            maxLength={4000}
          />
          <button
            className="primary-btn"
            disabled={draft.trim().length === 0 || sending}
            onClick={send}
          >
            {sending ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ChatBubble({ message }: { message: PublicChatMessage }) {
  // Banners for the fixed safety copy (DEC-24); bubbles for everything else.
  if (message.kind === "escalation") return <div className="banner warn">{message.body}</div>;
  if (message.kind === "redirect" || message.kind === "capped") {
    return <div className="banner">{message.body}</div>;
  }
  return <div className={`bubble ${message.sender}`}>{message.body}</div>;
}
