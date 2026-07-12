import { useEffect, useRef, useState } from "react";
import { api, ApiError, uploadToPresigned } from "../api";
import type { PublicPhoto } from "../types";

// Mirror the server caps (public.py) for friendly errors before the network.
const MAX_PHOTOS = 6;
const MAX_PHOTO_BYTES = 10 * 1024 * 1024;

/** Best-effort content hash: crypto.subtle is unavailable on http LAN phones
    (not a secure context) — the server accepts a missing hash, never a fake. */
async function sha256Hex(file: File): Promise<string | null> {
  if (!window.crypto?.subtle) return null;
  try {
    const buf = await window.crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  } catch {
    return null;
  }
}

export function Intake({ slug }: { slug: string }) {
  const [buildingName, setBuildingName] = useState<string | null>(null);
  const [badLink, setBadLink] = useState(false);
  const [description, setDescription] = useState("");
  const [contact, setContact] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusSlug, setStatusSlug] = useState<string | null>(null);
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
        <div className="center muted">This link isn’t valid. Ask your building manager for a new one.</div>
      </div>
    );
  }

  if (statusSlug) {
    const statusUrl = `${window.location.origin}${window.location.pathname}#/status/${statusSlug}`;
    return (
      <div className="shell">
        <div className="center">
          <div className="success-mark">✓</div>
          <h1 style={{ fontSize: 20, margin: "0 0 8px" }}>Got it — we’re on it.</h1>
          <p className="muted">Save this link to check progress or answer follow-up questions:</p>
          <p>
            <a className="linkbox" href={`#/status/${statusSlug}`}>
              {statusUrl}
            </a>
          </p>
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

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const photos: PublicPhoto[] = [];
      for (const f of files) {
        const presign = await api.publicPresign(slug, {
          filename: f.name,
          content_type: f.type,
          size_bytes: f.size,
        });
        await uploadToPresigned(presign.upload_url, f);
        photos.push({
          object_key: presign.object_key,
          content_type: f.type,
          sha256: await sha256Hex(f),
        });
      }
      const created = await api.publicIntake(slug, {
        description: description.trim(),
        contact: contact.trim(),
        photos,
      });
      setStatusSlug(created.status_slug);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "A photo failed to upload — remove photos or try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const ready = description.trim().length > 0 && contact.trim().length > 0;

  return (
    <div className="shell">
      <div className="login-wrap">
        <div className="brand">Report a problem</div>
        <p className="muted" style={{ margin: "0 0 12px" }}>
          {buildingName ?? "…"}
        </p>

        <label className="field">
          What’s wrong?
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
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

        <button className="primary-btn" disabled={!ready || submitting} onClick={submit}>
          {submitting ? "Sending…" : "Send report"}
        </button>
      </div>
    </div>
  );
}
