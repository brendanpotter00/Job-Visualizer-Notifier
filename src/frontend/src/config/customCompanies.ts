/**
 * Feature-flag config for custom (user-supplied) company sources.
 *
 * This flag is CLIENT-side only and is completely independent of the backend's
 * own `CUSTOM_COMPANY_SOURCES_ENABLED` setting. Turning this on does not turn
 * the server on: `POST /api/companies/resolve` answers 503 while the server
 * flag is off, and the UI surfaces that as its own error state. Both must be on
 * for the flow to work end to end.
 *
 * Default OFF. With the flag off the app must be byte-for-byte the same as
 * before this feature existed: no nav entry, no route, no network calls.
 */
export interface CustomCompaniesConfig {
  /** True only when `VITE_CUSTOM_COMPANIES_ENABLED` is exactly the string `'true'`. */
  isEnabled: boolean;
  /**
   * The 4-step discovery-progress checklist (E7 capture pivot). Its own flag, and
   * nested UNDER `isEnabled` — this is a presentation change inside a feature that
   * already ships dark, so it must be rollable back on its own without turning off
   * the whole My-Companies page.
   *
   * OFF is the default and OFF must render byte-for-byte what shipped before: the
   * health badge alone, no checklist, no job preview, no live view, and the same 15s
   * list poll. The backend always emits the checklist regardless — a payload field the
   * UI ignores is free, and it means flipping this on is a frontend-only deploy.
   */
  isDiscoveryProgressEnabled: boolean;
}

export const CUSTOM_COMPANIES_CONFIG: CustomCompaniesConfig = {
  // Strict `=== 'true'` (not truthiness) so a stray `0`, `false`, or an
  // accidentally-set-but-empty var can never switch the feature on.
  isEnabled: import.meta.env.VITE_CUSTOM_COMPANIES_ENABLED === 'true',
  isDiscoveryProgressEnabled: import.meta.env.VITE_DISCOVERY_PROGRESS_ENABLED === 'true',
};
