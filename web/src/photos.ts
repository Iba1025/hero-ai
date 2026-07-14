// Shared by form intake and chat intake: presign → direct-to-R2 PUT (INV-3).

import { api, uploadToPresigned } from "./api";
import type { PublicPhoto } from "./types";

// Mirror the server caps (public.py) for friendly errors before the network.
export const MAX_PHOTOS = 6;
export const MAX_PHOTO_BYTES = 10 * 1024 * 1024;

/** Best-effort content hash: crypto.subtle is unavailable on http LAN phones
    (not a secure context) — the server accepts a missing hash, never a fake. */
export async function sha256Hex(file: File): Promise<string | null> {
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

/** Client-side picker validation shared by the opener and the mid-chat
    composer: returns the new file list, reporting problems via onError. */
export function appendPickedPhotos(
  current: File[],
  picked: FileList | null,
  onError: (msg: string) => void,
): File[] {
  if (!picked) return current;
  const next = [...current];
  for (const f of Array.from(picked)) {
    if (next.length >= MAX_PHOTOS) {
      onError(`At most ${MAX_PHOTOS} photos.`);
      break;
    }
    if (!f.type.startsWith("image/")) {
      onError("Only photos can be attached.");
      continue;
    }
    if (f.size > MAX_PHOTO_BYTES) {
      onError(`“${f.name}” is too large (max ${MAX_PHOTO_BYTES / (1024 * 1024)} MB).`);
      continue;
    }
    next.push(f);
  }
  return next;
}

type PresignFn = (body: {
  filename: string;
  content_type: string;
  size_bytes: number;
}) => Promise<{ upload_url: string; object_key: string }>;

async function uploadAll(files: File[], presign: PresignFn): Promise<PublicPhoto[]> {
  const photos: PublicPhoto[] = [];
  for (const f of files) {
    const grant = await presign({ filename: f.name, content_type: f.type, size_bytes: f.size });
    await uploadToPresigned(grant.upload_url, f);
    photos.push({
      object_key: grant.object_key,
      content_type: f.type,
      sha256: await sha256Hex(f),
    });
  }
  return photos;
}

/** Presign + upload each photo; returns the pointers the intake body needs. */
export function uploadPhotos(slug: string, files: File[]): Promise<PublicPhoto[]> {
  return uploadAll(files, (body) => api.publicPresign(slug, body));
}

/** Same, but presigned via the status link (BL-22 mid-chat photos). */
export function uploadPhotosMidChat(statusSlug: string, files: File[]): Promise<PublicPhoto[]> {
  return uploadAll(files, (body) => api.publicStatusPresign(statusSlug, body));
}
