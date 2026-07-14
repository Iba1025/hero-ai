import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { navigate } from "../App";
import { tenantErrorCopy } from "../errors";
import { CameraIcon, NovaHeader, NovaStaticBubble, SendIcon } from "../nova-ui";
import { appendPickedPhotos, uploadPhotos } from "../photos";

/** Nova chat opener (DEC-23, reskinned per DEC-26): the first message IS the
    intake. A redirected opener (DEC-24) creates nothing — the fixed copy is
    shown and the tenant can rephrase. On success we go straight to the
    status page, which renders the live conversation. */
export function Chat({ slug }: { slug: string }) {
  const [buildingName, setBuildingName] = useState<string | null>(null);
  const [badLink, setBadLink] = useState(false);
  const [message, setMessage] = useState("");
  const [contact, setContact] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [redirectCopy, setRedirectCopy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .publicBuilding(slug)
      .then((b) => setBuildingName(b.name))
      .catch(() => setBadLink(true));
  }, [slug]);

  if (badLink) {
    return (
      <div className="nova-shell">
        <NovaHeader />
        <div className="nova-chat">
          <NovaStaticBubble>
            This link isn’t valid. Ask your building manager for a new one.
          </NovaStaticBubble>
        </div>
      </div>
    );
  }

  const addFiles = (picked: FileList | null) => {
    setError(null);
    setFiles(appendPickedPhotos(files, picked, setError));
    if (fileInput.current) fileInput.current.value = "";
  };

  const send = async () => {
    setSending(true);
    setError(null);
    setRedirectCopy(null);
    try {
      const photos = await uploadPhotos(slug, files);
      const started = await api.publicChatStart(slug, {
        message: message.trim(),
        contact: contact.trim(),
        photos,
      });
      if (started.status_slug) {
        navigate(`/status/${started.status_slug}`);
        return;
      }
      // DEC-24 redirect: nothing was created — show the fixed copy, keep the
      // composer so the tenant can describe the maintenance problem instead.
      setRedirectCopy(started.reply.body);
      setMessage("");
    } catch (err) {
      setError(tenantErrorCopy(err, "report"));
    } finally {
      setSending(false);
    }
  };

  const ready = message.trim().length > 0 && contact.trim().length > 0;

  return (
    <div className="nova-shell">
      <NovaHeader />

      <div className="nova-chat">
        <NovaStaticBubble>
          Hi — tell me what’s wrong in your home
          {buildingName ? ` at ${buildingName}` : ""} and I’ll get it looked at. A photo helps if
          you have one.
        </NovaStaticBubble>
        {redirectCopy && <div className="banner">{redirectCopy}</div>}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="nova-footer">
        {files.length > 0 && (
          <div className="nova-chips">
            {files.map((f, i) => (
              <button
                key={`${f.name}-${i}`}
                className="chip"
                onClick={() => setFiles(files.filter((_, j) => j !== i))}
              >
                {f.name} ✕
              </button>
            ))}
          </div>
        )}

        <label className="nova-field">
          Phone or email — so we can reach you with questions
          <input
            type="text"
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            placeholder="555-0123 or you@example.com"
            maxLength={200}
          />
        </label>

        <div className="nova-composer">
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            multiple
            capture="environment"
            onChange={(e) => addFiles(e.target.files)}
            style={{ display: "none" }}
          />
          <button
            className="round-btn"
            aria-label="Add a photo"
            onClick={() => fileInput.current?.click()}
          >
            <CameraIcon />
          </button>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Type your message…"
            maxLength={4000}
            rows={1}
          />
          <button
            className="round-btn send"
            aria-label="Send"
            disabled={!ready || sending}
            onClick={send}
          >
            <SendIcon />
          </button>
        </div>
      </div>
    </div>
  );
}
