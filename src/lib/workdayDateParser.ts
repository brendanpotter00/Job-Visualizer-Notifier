/**
 * TEMPORARY DATE PARSER - Will be updated after investigating actual API response
 *
 * Parses Workday's relative date strings into ISO 8601 timestamps.
 * WARNING: Relative dates are insufficient for historical trend visualization.
 * This is a fallback implementation - actual API may have absolute timestamps.
 *
 * Handles the following formats:
 * - "Posted Today" → midnight of current day
 * - "Posted Yesterday" → midnight of previous day
 * - "Posted X Days Ago" → X days ago at midnight
 * - "Posted X+ Days Ago" → (X+1) days ago at midnight (distinguishes from exact X days)
 *
 * @param postedOn - Relative date string from Workday (e.g., "Posted Today")
 * @returns ISO 8601 timestamp string (always at midnight UTC)
 *
 * @example
 * parseWorkdayDate("Posted Today") // "2025-11-27T00:00:00.000Z"
 * parseWorkdayDate("Posted Yesterday") // "2025-11-26T00:00:00.000Z"
 * parseWorkdayDate("Posted 30 Days Ago") // "2025-10-28T00:00:00.000Z" (exactly 30 days)
 * parseWorkdayDate("Posted 30+ Days Ago") // "2025-10-27T00:00:00.000Z" (31 days - beyond 30 day threshold)
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
    const today = new Date(now);
    today.setUTCHours(0, 0, 0, 0);
    return today.toISOString();
  }

  // "Posted Yesterday"
  if (lowerPosted.includes('yesterday')) {
    const yesterday = new Date(now);
    yesterday.setUTCDate(yesterday.getUTCDate() - 1);
    yesterday.setUTCHours(0, 0, 0, 0);
    return yesterday.toISOString();
  }

  // "Posted X Days Ago" or "Posted X+ Days Ago"
  const daysMatch = lowerPosted.match(/(\d+)(\+)?\s*days?\s*ago/);
  if (daysMatch) {
    const baseDays = parseInt(daysMatch[1], 10);
    const isPlusRange = !!daysMatch[2]; // true if "+" is present
    const daysAgo = isPlusRange ? baseDays + 1 : baseDays;

    const date = new Date(now);
    date.setUTCDate(date.getUTCDate() - daysAgo);
    date.setUTCHours(0, 0, 0, 0);
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
