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

/** Presign + upload each photo; returns the pointers the intake body needs. */
export async function uploadPhotos(slug: string, files: File[]): Promise<PublicPhoto[]> {
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
  return photos;
}
