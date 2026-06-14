/**
 * Utility functions for location filtering and detection
 */

import type { JobLocation } from '../types';

/**
 * All 50 US state abbreviations
 */
export const US_STATE_CODES = [
  'AL',
  'AK',
  'AZ',
  'AR',
  'CA',
  'CO',
  'CT',
  'DE',
  'FL',
  'GA',
  'HI',
  'ID',
  'IL',
  'IN',
  'IA',
  'KS',
  'KY',
  'LA',
  'ME',
  'MD',
  'MA',
  'MI',
  'MN',
  'MS',
  'MO',
  'MT',
  'NE',
  'NV',
  'NH',
  'NJ',
  'NM',
  'NY',
  'NC',
  'ND',
  'OH',
  'OK',
  'OR',
  'PA',
  'RI',
  'SC',
  'SD',
  'TN',
  'TX',
  'UT',
  'VT',
  'VA',
  'WA',
  'WV',
  'WI',
  'WY',
];

/**
 * Pre-compiled RegExp for US state code detection
 * Matches locations ending with ", XX" where XX is a US state code
 */
const STATE_PATTERN = new RegExp(`, (${US_STATE_CODES.join('|')})$`);

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
  return STATE_PATTERN.test(location);
}

/**
 * Display label for a job's location.
 *
 * Prefers the normalized canonical tags (joined), which are clean and
 * deduplicated, and falls back to the raw scraped string for jobs that have
 * not been normalized yet. Returns undefined when neither is available.
 *
 * @example
 * formatJobLocations([{ canonicalName: 'Austin, TX, US', ... }]) // "Austin, TX, US"
 * formatJobLocations([], 'Austin - 5323') // "Austin - 5323" (raw fallback)
 */
export function formatJobLocations(
  locations: JobLocation[] | undefined,
  rawFallback?: string
): string | undefined {
  if (locations && locations.length > 0) {
    return locations.map((loc) => loc.canonicalName).join('; ');
  }
  return rawFallback || undefined;
}
