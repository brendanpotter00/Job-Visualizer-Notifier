import { format } from 'date-fns';

export interface DayPoint {
  /** UTC start-of-day in ms. */
  time: number;
  /** Short axis label, e.g. `Jan 14`. */
  label: string;
  /**
   * For `bucketCumulative`, the running cumulative total through
   * end-of-day(time). For `bucketPerDay`, the count of signups on that
   * specific UTC day.
   */
  count: number;
}

const MS_PER_DAY = 86_400_000;

function utcStartOfDay(t: number): number {
  const d = new Date(t);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

interface DailyGrid {
  startDay: number;
  endDay: number;
  perDay: Map<number, number>;
}

function buildDailyGrid(createdAts: string[]): DailyGrid | null {
  const times: number[] = [];
  for (const iso of createdAts) {
    const t = new Date(iso).getTime();
    if (!Number.isNaN(t)) times.push(t);
  }
  if (times.length === 0) return null;

  // `Math.min(...times)` hits the JS argument-count limit (~65k on V8) past
  // a certain user count; reduce-loop to tolerate a large roster.
  let min = Infinity;
  for (const t of times) if (t < min) min = t;

  const perDay = new Map<number, number>();
  for (const t of times) {
    const key = utcStartOfDay(t);
    perDay.set(key, (perDay.get(key) ?? 0) + 1);
  }

  return {
    startDay: utcStartOfDay(min),
    endDay: utcStartOfDay(Date.now()),
    perDay,
  };
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
  const grid = buildDailyGrid(createdAts);
  if (!grid) return [];

  const points: DayPoint[] = [];
  let running = 0;
  for (let day = grid.startDay; day <= grid.endDay; day += MS_PER_DAY) {
    running += grid.perDay.get(day) ?? 0;
    points.push({
      time: day,
      label: format(new Date(day), 'MMM d'),
      count: running,
    });
  }
  return points;
}

/**
 * Bucket signups by UTC calendar day and emit one point per day from the first
 * signup through "today" inclusive. Each point's `count` is the number of
 * signups whose timestamp falls *within* that UTC day (a daily delta, not a
 * running total). Days with no signups emit a point with `count: 0` so the
 * bar chart shows gap days at zero rather than skipping them.
 */
export function bucketPerDay(createdAts: string[]): DayPoint[] {
  const grid = buildDailyGrid(createdAts);
  if (!grid) return [];

  const points: DayPoint[] = [];
  for (let day = grid.startDay; day <= grid.endDay; day += MS_PER_DAY) {
    points.push({
      time: day,
      label: format(new Date(day), 'MMM d'),
      count: grid.perDay.get(day) ?? 0,
    });
  }
  return points;
}
