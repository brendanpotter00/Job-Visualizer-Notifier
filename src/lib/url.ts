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
 * Get the company ID from the URL query parameters
 * @returns The company ID if valid, otherwise undefined
 */
export function getCompanyFromURL(): string | undefined {
  const searchParams = new URLSearchParams(window.location.search);
  const companyId = searchParams.get(COMPANY_PARAM);

  if (!companyId) {
    return undefined;
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
 * @returns The company ID to use for initialization
 */
export function getInitialCompanyId(): string {
  return getCompanyFromURL() || DEFAULT_COMPANY_ID;
}
