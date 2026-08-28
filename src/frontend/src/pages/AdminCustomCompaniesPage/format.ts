/**
 * Small display helpers shared by the three Custom Companies tables and the
 * attempt detail panel. React-free so they are testable without a render, and
 * kept out of `statusChips.ts` because that module is only about the chip
 * vocabulary.
 */

/**
 * A timestamp as the tables render it: "Aug 28, 01:10". Falls back to an em
 * dash for null and for anything `Date` cannot parse, because an
 * "Invalid Date" in a cell is worse than an admitted blank.
 */
export function formatTimestamp(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** A date with no clock, for the rollup's "first → last" span: "Aug 20". */
export function formatDay(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * The board URL as the table shows it — scheme and any trailing slash removed.
 *
 * Purely cosmetic: `submittedUrl` is what the user actually pasted and is shown
 * in full in the detail panel. Here the column is narrow and "https://" is the
 * same eight characters on every row, so it earns nothing.
 */
export function stripScheme(url: string): string {
  return url.replace(/^https?:\/\//i, '').replace(/\/$/, '');
}

/** "44 s" / "3 m 20 s" for `decidedInS`. Null-safe. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—';
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes} m` : `${minutes} m ${rest} s`;
}

/**
 * The failed share of all attempts, as a whole percent. Returns null when there
 * are no attempts at all — 0/0 is not "0 %", it is "no answer yet", and a
 * confident red "0 %" on an empty database would be a lie.
 */
export function failedPercent(failedCount: number, attemptCount: number): number | null {
  if (attemptCount <= 0) return null;
  return Math.round((failedCount / attemptCount) * 100);
}
