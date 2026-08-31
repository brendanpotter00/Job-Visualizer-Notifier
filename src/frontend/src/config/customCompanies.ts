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
}

export const CUSTOM_COMPANIES_CONFIG: CustomCompaniesConfig = {
  // Strict `=== 'true'` (not truthiness) so a stray `0`, `false`, or an
  // accidentally-set-but-empty var can never switch the feature on.
  isEnabled: import.meta.env.VITE_CUSTOM_COMPANIES_ENABLED === 'true',
};
