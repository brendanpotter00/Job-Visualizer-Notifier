import { format } from 'date-fns';

export interface DayPoint {
  /** UTC start-of-day in ms. */
  time: number;
  /** Short axis label, e.g. `Jan 14`. */
  label: string;
  /** Running cumulative total of signups through end-of-day(time). */
  count: number;
}

const MS_PER_DAY = 86_400_000;

function utcStartOfDay(t: number): number {
  const d = new Date(t);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

/**
 * Bucket signups by UTC calendar day and emit one point per day from the first
 * signup through "today" inclusive. Each point's `count` is the running
 * cumulative total of signups whose timestamp is `<= end-of-day(point.time)`.
 *
 * Forward-fill to today (rather than just the latest signup) is intentional:
 * a flat trailing segment communicates "no recent signups" instead of leaving
 * the chart silently truncated at the last signup date.
 */
export function bucketCumulative(createdAts: string[]): DayPoint[] {
  const times: number[] = [];
  for (const iso of createdAts) {
    const t = new Date(iso).getTime();
    if (!Number.isNaN(t)) times.push(t);
  }
  if (times.length === 0) return [];

  // `Math.min(...times)` hits the JS argument-count limit (~65k on V8) past
  // a certain user count; reduce-loop to tolerate a large roster.
  let min = Infinity;
  for (const t of times) if (t < min) min = t;

  const startDay = utcStartOfDay(min);
  const endDay = utcStartOfDay(Date.now());

  const perDay = new Map<number, number>();
  for (const t of times) {
    const key = utcStartOfDay(t);
    perDay.set(key, (perDay.get(key) ?? 0) + 1);
  }

  const points: DayPoint[] = [];
  let running = 0;
  for (let day = startDay; day <= endDay; day += MS_PER_DAY) {
    running += perDay.get(day) ?? 0;
    points.push({
      time: day,
      label: format(new Date(day), 'MMM d'),
      count: running,
    });
  }
  return points;
}
