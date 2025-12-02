import { getCompanyById } from '../config/companies';

/**
 * Company lookup utilities
 * Provides helper functions for working with company IDs and names
 */

/**
 * Get company name by ID
 * Returns the company name if found, otherwise returns the ID as fallback
 *
 * @param id - Company ID to lookup
 * @returns Company name or ID if company not found
 *
 * @example
 * ```typescript
 * const name = getCompanyNameById('spacex'); // Returns: "SpaceX"
 * const unknown = getCompanyNameById('unknown'); // Returns: "unknown"
 * ```
 */
export function getCompanyNameById(id: string): string {
  const company = getCompanyById(id);
  return company?.name || id;
}

/**
 * Map array of company IDs to objects with id and name properties
 * Filters out invalid/unknown company IDs and sorts by name
 *
 * @param ids - Array of company IDs
 * @returns Sorted array of {id, name} objects
 *
 * @example
 * ```typescript
 * const companies = mapCompanyIdsToObjects(['spacex', 'anthropic']);
 * // Returns: [
 * //   { id: 'anthropic', name: 'Anthropic' },
 * //   { id: 'spacex', name: 'SpaceX' }
 * // ]
 * ```
 */
export function mapCompanyIdsToObjects(ids: string[]): Array<{ id: string; name: string }> {
  return ids
    .map((id) => ({
      id,
      name: getCompanyNameById(id),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Check if a company ID exists in the configuration
 *
 * @param id - Company ID to check
 * @returns True if company exists, false otherwise
 *
 * @example
 * ```typescript
 * isValidCompanyId('spacex'); // Returns: true
 * isValidCompanyId('unknown'); // Returns: false
 * ```
 */
export function isValidCompanyId(id: string): boolean {
  return getCompanyById(id) !== undefined;
}
