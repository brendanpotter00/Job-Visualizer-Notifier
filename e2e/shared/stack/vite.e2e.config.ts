// e2e-only Vite config (PLAN.md §2, "Trap 1" and "Trap 2").
//
// Trap 1: `vercel dev` cannot be pointed at :8201 reliably — Vercel Dev's
// cloud env vars override `.env.local` AND shell env vars for `api/*.ts`
// (root CLAUDE.md gotcha #3). So the e2e frontend runs under plain `vite dev`
// instead, at the honest cost that the Vercel proxy layer (`api/users.ts`,
// `api/companies.ts`) is NOT exercised by this suite — those proxies are thin
// and separately covered; see CASES.md's non-coverage note.
//
// Trap 2: the checked-in `src/frontend/vite.config.ts` proxies only
// `/api/jobs`, `/api/users`, `/api/lever`, `/api/ashby` — `POST
// /api/companies/resolve` would 404 under it. This config proxies the WHOLE
// `/api` prefix at :8201 instead of a path list.
//
// `root` points at `src/frontend` so this resolves the same `@vitejs/plugin-react`
// and picks up `src/frontend/.env.local` (VITE_AUTH0_DOMAIN, VITE_AUTH0_CLIENT_ID,
// VITE_CUSTOM_COMPANIES_ENABLED=true, VITE_DISCOVERY_PROGRESS_ENABLED=true) as its
// envDir automatically — nothing here duplicates those values.
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, '../../../src/frontend');

// Ports come from the environment `stack_up.sh` exports, defaulting to the
// pair that shipped. A section with its own stack (`subcategories` runs on
// 8203/3203) reuses this config rather than forking it — see
// `add-companies/PLAN.md` §1's rule 2.
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 3201);
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8201);

export default defineConfig({
  root: frontendRoot,
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: FRONTEND_PORT,
    strictPort: true,
    open: false,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${BACKEND_PORT}`,
        changeOrigin: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: 'dist-e2e',
    sourcemap: true,
  },
});
