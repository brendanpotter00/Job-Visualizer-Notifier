/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_POSTHOG_KEY?: string;
  readonly VITE_POSTHOG_HOST?: string;
  // Auth vars (existing)
  readonly VITE_AUTH0_DOMAIN?: string;
  readonly VITE_AUTH0_CLIENT_ID?: string;
  readonly VITE_AUTH0_REDIRECT_URI?: string;
  readonly VITE_AUTH0_AUDIENCE?: string;
  readonly VITE_GOOGLE_CLIENT_ID?: string;
  readonly VITE_AUTH_BYPASS?: string;
  // Custom (user-added) company sources, and the discovery-progress checklist inside it.
  readonly VITE_CUSTOM_COMPANIES_ENABLED?: string;
  readonly VITE_DISCOVERY_PROGRESS_ENABLED?: string;
  // Backend origin for the LOCAL-DEV-ONLY custom-company reset on the QA page.
  // Only needed when the backend is not on :8000 (per-worktree ports).
  readonly VITE_DEV_RESET_BACKEND_URL?: string;
  // WebMCP tool surface — '1' turns on the e2e agent-driving shim + tool
  // registration (see src/webmcp). Unset in every normal/prod build.
  readonly VITE_WEBMCP?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
