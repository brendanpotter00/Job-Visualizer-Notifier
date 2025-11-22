/**
 * Utility functions for location filtering and detection
 */

/**
 * All 50 US state abbreviations
 */
export const US_STATE_CODES = [
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
  'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
  'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
  'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
  'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
];

/**
 * Determines if a location string represents a United States location.
 *
 * Detection logic:
 * - Matches locations ending with ", XX" where XX is a US state code (e.g., "San Francisco, CA")
 * - Also matches "Remote" locations (treated as US-based per configuration)
 *
 * @param location - The location string to check
 * @returns true if the location is US-based or Remote, false otherwise
 *
 * @example
 * isUnitedStatesLocation("San Francisco, CA") // true
 * isUnitedStatesLocation("Remote") // true
 * isUnitedStatesLocation("London, UK") // false
 * isUnitedStatesLocation("New York") // false (missing state code)
 * isUnitedStatesLocation(undefined) // false
 */
export function isUnitedStatesLocation(location: string | undefined): boolean {
  if (!location) {
    return false;
  }

  // Check for "Remote" location
  if (location.toLowerCase() === 'remote') {
    return true;
  }

  // Check for ", XX" pattern where XX is a US state code
  const statePattern = new RegExp(`, (${US_STATE_CODES.join('|')})$`);
  return statePattern.test(location);
}
