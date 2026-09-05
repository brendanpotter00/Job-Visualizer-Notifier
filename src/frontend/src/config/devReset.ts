/**
 * Config for the LOCAL-DEVELOPMENT-ONLY custom-company reset (the QA page's
 * "Danger zone" panel).
 *
 * WHY THIS TALKS TO THE BACKEND DIRECTLY. Every other call in this app goes
 * through a Vercel serverless proxy (`/api/users?path=...`). This one must not:
 * the whole point of `POST /api/users/dev-reset` is that it is unreachable from
 * the public internet, so it is deliberately absent from every `PROXIED_ROUTES`
 * allowlist (pinned by `api/tests/test_proxy_path_allowlists.py`). A proxy hop
 * would be a second front door onto a route whose entire safety story is "there
 * is no door". So the button calls `http://localhost:<backend port>` directly,
 * which only works on a machine that is running the backend — exactly the
 * machine the feature is for.
 *
 * WHICH PORT. `LOCAL_BACKEND_URL` already exists for the serverless proxies and
 * varies per worktree (8000, 8100, ...). That is a server-side var and Vite
 * cannot read it, so the browser side needs its own: set
 * `VITE_DEV_RESET_BACKEND_URL` in `.env.local` if your backend is not on 8000.
 */

/**
 * True only in a dev server build. `import.meta.env.DEV` is statically replaced
 * at build time, so in a production bundle every branch guarded by this is
 * removed entirely — the panel and its fetch calls are not shipped, not merely
 * hidden.
 */
export const IS_DEV_BUILD = import.meta.env.DEV;

/** Backend origin for the direct (un-proxied) dev-reset calls. */
export const DEV_RESET_BACKEND_URL =
  import.meta.env.VITE_DEV_RESET_BACKEND_URL || 'http://localhost:8000';

/** The one path, spelled once. Mirrors the backend's `/api/users/dev-reset`. */
export const DEV_RESET_PATH = '/api/users/dev-reset';

export const devResetUrl = (query = ''): string =>
  `${DEV_RESET_BACKEND_URL}${DEV_RESET_PATH}${query}`;
