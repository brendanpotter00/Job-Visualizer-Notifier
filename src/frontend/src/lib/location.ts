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
 * US state code -> full name. Used to synthesize selectable "<State>, US" parent
 * options (so a state is pickable even when no job is tagged at state level) and
 * to resolve a synthesized state label back to its region code when matching.
 * Includes DC for completeness.
 */
export const US_STATE_NAMES: Record<string, string> = {
  AL: 'Alabama',
  AK: 'Alaska',
  AZ: 'Arizona',
  AR: 'Arkansas',
  CA: 'California',
  CO: 'Colorado',
  CT: 'Connecticut',
  DC: 'District of Columbia',
  DE: 'Delaware',
  FL: 'Florida',
  GA: 'Georgia',
  HI: 'Hawaii',
  ID: 'Idaho',
  IL: 'Illinois',
  IN: 'Indiana',
  IA: 'Iowa',
  KS: 'Kansas',
  KY: 'Kentucky',
  LA: 'Louisiana',
  ME: 'Maine',
  MD: 'Maryland',
  MA: 'Massachusetts',
  MI: 'Michigan',
  MN: 'Minnesota',
  MS: 'Mississippi',
  MO: 'Missouri',
  MT: 'Montana',
  NE: 'Nebraska',
  NV: 'Nevada',
  NH: 'New Hampshire',
  NJ: 'New Jersey',
  NM: 'New Mexico',
  NY: 'New York',
  NC: 'North Carolina',
  ND: 'North Dakota',
  OH: 'Ohio',
  OK: 'Oklahoma',
  OR: 'Oregon',
  PA: 'Pennsylvania',
  RI: 'Rhode Island',
  SC: 'South Carolina',
  SD: 'South Dakota',
  TN: 'Tennessee',
  TX: 'Texas',
  UT: 'Utah',
  VT: 'Vermont',
  VA: 'Virginia',
  WA: 'Washington',
  WV: 'West Virginia',
  WI: 'Wisconsin',
  WY: 'Wyoming',
};

/** Reverse of US_STATE_NAMES: upper-cased full name -> code, e.g. "CALIFORNIA" -> "CA". */
export const US_STATE_NAME_TO_CODE: Record<string, string> = Object.fromEntries(
  Object.entries(US_STATE_NAMES).map(([code, name]) => [name.toUpperCase(), code])
);

/** Synthesized state-tier option label, e.g. "California, US". */
export function stateOptionLabel(stateCode: string): string {
  return `${US_STATE_NAMES[stateCode]}, US`;
}

/** Strip a trailing ", US" and upper-case, for resolving a synthesized state label. */
export function stripUsSuffix(label: string): string {
  return label
    .replace(/,\s*US$/i, '')
    .trim()
    .toUpperCase();
}

/**
 * Build the ordered, deduped list of selectable Location-filter options from a
 * set of jobs' canonical tags, SYNTHESIZING parent tiers so the hierarchy is
 * navigable:
 *
 *   Tier 1: "United States" meta-option (when any tag has country 'US')
 *   Tier 2: "<State>, US" for every US 2-letter region present — even when no
 *           job is tagged at state level (e.g. cities exist but no state row)
 *   Tier 3: every real tag's canonicalName (cities, non-US, remote)
 *
 * Each tier is alphabetical; broad options float to the top. A synthesized state
 * label is deduped against any identical real region tag. Pairs with
 * `matchesLocation`, which does the hierarchical containment at filter time.
 */
export function buildLocationOptions(jobs: { locations?: JobLocation[] }[]): string[] {
  const realNames = new Set<string>();
  const stateCodes = new Set<string>();
  let hasUS = false;

  for (const job of jobs) {
    for (const loc of job.locations ?? []) {
      realNames.add(loc.canonicalName);
      const country = loc.country?.trim().toUpperCase();
      const region = loc.region?.trim().toUpperCase();
      if (country === 'US') {
        hasUS = true;
        if (region && US_STATE_NAMES[region]) stateCodes.add(region);
      }
    }
  }

  const stateOptions = Array.from(stateCodes)
    .map(stateOptionLabel)
    .sort((a, b) => a.localeCompare(b));
  const stateSet = new Set(stateOptions);

  const tagOptions = Array.from(realNames)
    .filter((name) => !stateSet.has(name) && name !== 'United States')
    .sort((a, b) => a.localeCompare(b));

  const out: string[] = [];
  if (hasUS) out.push('United States');
  out.push(...stateOptions, ...tagOptions);
  // Final guard against a real "United States" country tag duplicating the meta.
  return Array.from(new Set(out));
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
