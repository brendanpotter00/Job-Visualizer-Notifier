import { getCompanyById } from '../config/companies';

/**
 * URL parameter name for company selection
 */
export const COMPANY_PARAM = 'company';

/**
 * Default company ID when none specified or invalid
 */
export const DEFAULT_COMPANY_ID = 'spacex';

/**
 * The raw `?company=` value, unvalidated — `null` when the param is absent.
 *
 * Exists so a caller can decide HOW to validate before it can. `/companies`
 * selects its company synchronously on mount, but a `u-<id>` cannot be
 * validated until the caller's own (authenticated) company list resolves; the
 * raw value is what tells the loader whether it is even in that situation, so
 * public deep links keep today's exact timing. See `useCompanyLoader`.
 */
export function getRawCompanyParam(): string | null {
  return new URLSearchParams(window.location.search).get(COMPANY_PARAM);
}

/**
 * Get the company ID from the URL query parameters
 *
 * @param extraValidIds - Ids that are valid for THIS viewer on top of the
 *   compile-time roster: the custom boards they own. Omitted (the default) the
 *   behaviour is exactly what it has always been — the static roster and
 *   nothing else — which is what a signed-out visitor and a flag-off build get.
 * @returns The company ID if valid, otherwise undefined
 */
export function getCompanyFromURL(extraValidIds?: ReadonlySet<string>): string | undefined {
  const companyId = getRawCompanyParam();

  if (!companyId) {
    return undefined;
  }

  // The viewer's own boards first: they are runtime ids that `getCompanyById`
  // has never heard of, and asking it would only ever answer "no".
  if (extraValidIds?.has(companyId)) {
    return companyId;
  }

  // Validate that the company exists in our configuration
  const company = getCompanyById(companyId);
  return company ? companyId : undefined;
}

/**
 * Update the URL with the selected company ID
 * Creates a new history entry for browser back/forward navigation
 * @param companyId - The company ID to set in the URL
 */
export function updateURLWithCompany(companyId: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set(COMPANY_PARAM, companyId);
  window.history.pushState({}, '', url.toString());
}

/**
 * Get the initial company ID (from URL or default)
 * @param extraValidIds - See `getCompanyFromURL`.
 * @returns The company ID to use for initialization
 */
export function getInitialCompanyId(extraValidIds?: ReadonlySet<string>): string {
  return getCompanyFromURL(extraValidIds) || DEFAULT_COMPANY_ID;
}
