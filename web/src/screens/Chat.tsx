import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { navigate } from "../App";
import { tenantErrorCopy } from "../errors";
import { MAX_PHOTO_BYTES, MAX_PHOTOS, uploadPhotos } from "../photos";

/** Nova chat opener (Phase 5 STEP 4, DEC-23): the first message IS the
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
      <div className="shell">
        <div className="center muted">
          This link isn’t valid. Ask your building manager for a new one.
        </div>
      </div>
    );
  }

  const addFiles = (picked: FileList | null) => {
    if (!picked) return;
    setError(null);
    const next = [...files];
    for (const f of Array.from(picked)) {
      if (next.length >= MAX_PHOTOS) {
        setError(`At most ${MAX_PHOTOS} photos.`);
        break;
      }
      if (!f.type.startsWith("image/")) {
        setError("Only photos can be attached.");
        continue;
      }
      if (f.size > MAX_PHOTO_BYTES) {
        setError(`“${f.name}” is too large (max ${MAX_PHOTO_BYTES / (1024 * 1024)} MB).`);
        continue;
      }
      next.push(f);
    }
    setFiles(next);
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
    <div className="shell">
      <div className="login-wrap">
        <div className="brand">Message us about a problem</div>
        <p className="muted" style={{ margin: "0 0 12px" }}>
          {buildingName ?? "…"}
        </p>

        <div className="chat-log">
          <div className="bubble nova">
            Hi — tell me what’s wrong in your home and I’ll get it looked at. A photo helps if
            you have one.
          </div>
          {redirectCopy && <div className="banner">{redirectCopy}</div>}
        </div>

        <label className="field">
          What’s wrong?
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="e.g. The radiator in the living room is cold and makes a banging noise"
            maxLength={4000}
          />
        </label>

        <label className="field">
          Photos (optional)
          <input
            ref={fileInput}
            type="file"
            accept="image/*"
            multiple
            capture="environment"
            onChange={(e) => addFiles(e.target.files)}
            style={{ marginTop: 6 }}
          />
        </label>
        {files.length > 0 && (
          <div className="chips">
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

        <label className="field">
          Phone or email — so we can reach you with questions
          <input
            type="text"
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            placeholder="555-0123 or you@example.com"
            maxLength={200}
          />
        </label>

        {error && <div className="error">{error}</div>}

        <button className="primary-btn" disabled={!ready || sending} onClick={send}>
          {sending ? "Sending…" : "Send"}
        </button>
      </div>
    </div>
  );
}
