/**
 * TEMPORARY DATE PARSER - Will be updated after investigating actual API response
 *
 * Parses Workday's relative date strings into ISO 8601 timestamps.
 * WARNING: Relative dates are insufficient for historical trend visualization.
 * This is a fallback implementation - actual API may have absolute timestamps.
 *
 * @param postedOn - Relative date string from Workday (e.g., "Posted Today")
 * @returns ISO 8601 timestamp string
 *
 * @example
 * parseWorkdayDate("Posted Today") // "2025-11-27T00:00:00.000Z"
 * parseWorkdayDate("Posted Yesterday") // "2025-11-26T00:00:00.000Z"
 * parseWorkdayDate("Posted 30+ Days Ago") // "2025-10-28T00:00:00.000Z"
 */
export function parseWorkdayDate(postedOn?: string): string {
  const now = new Date();

  if (!postedOn) {
    // Default to current timestamp if not provided
    return now.toISOString();
  }

  const lowerPosted = postedOn.toLowerCase();

  // "Posted Today"
  if (lowerPosted.includes('today')) {
    return new Date(now.setHours(0, 0, 0, 0)).toISOString();
  }

  // "Posted Yesterday"
  if (lowerPosted.includes('yesterday')) {
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    yesterday.setHours(0, 0, 0, 0);
    return yesterday.toISOString();
  }

  // "Posted X Days Ago" or "Posted X+ Days Ago"
  const daysMatch = lowerPosted.match(/(\d+)\+?\s*days?\s*ago/);
  if (daysMatch) {
    const daysAgo = parseInt(daysMatch[1], 10);
    const date = new Date(now);
    date.setDate(date.getDate() - daysAgo);
    date.setHours(0, 0, 0, 0);
    return date.toISOString();
  }

  // Fallback: if it's already an ISO date, return it
  // Otherwise, return current timestamp
  try {
    const parsed = new Date(postedOn);
    if (!isNaN(parsed.getTime())) {
      return parsed.toISOString();
    }
  } catch {
    // Invalid date, fall through to default
  }

  return now.toISOString();
}
