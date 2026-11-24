/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Backend already serves every route under /api, so no path rewrite is needed —
// the client's fetch("/api/…") is byte-identical in dev (proxied) and prod
// (same-origin). Point the proxy at the local dashboard API (DASHBOARD_PORT).
const API_PORT = Number(process.env.DASHBOARD_PORT ?? 8788);

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${API_PORT}`,
        changeOrigin: false,
      },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
  test: {
    environment: "jsdom",
    globals: false, // tests import { describe, it, expect, vi } from "vitest"
    setupFiles: ["./src/test/setup.ts"],
    clearMocks: true,
    restoreMocks: true,
    unstubGlobals: true, // auto-restore vi.stubGlobal("fetch", …) between tests
    coverage: { provider: "v8", include: ["src/**/*.{ts,tsx}"] },
  },
});
