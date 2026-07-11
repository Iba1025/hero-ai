import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies API prefixes to FastAPI so the session cookie is
// first-party on both laptop and phone (no CORS / Secure-cookie friction).
// Point VITE_API_PROXY_TARGET elsewhere if the API is not on localhost:8000.
const target = process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // reachable from a phone on the same network
    proxy: Object.fromEntries(
      ["/auth", "/tickets", "/outcomes", "/uploads"].map((p) => [p, { target, changeOrigin: true }]),
    ),
  },
});
