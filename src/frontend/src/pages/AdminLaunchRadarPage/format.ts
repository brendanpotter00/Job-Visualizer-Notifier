// Pure formatting helpers for the Launch Radar admin page. No React here, so
// every sentence the cards print is unit tested in isolation
// (__tests__/pages/AdminLaunchRadarPage/format.test.ts).

import type {
  LaunchRadarAts,
  LaunchRadarAtsProvider,
  LaunchRadarRound,
  LaunchRadarStats,
  LaunchRadarTally,
} from '../../features/admin/launchRadarTypes';

function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * "Oct 7". Always UTC: the loop stamps UTC and the event dates are date-only
 * strings (`2026-09-17`), which `Date` parses as UTC midnight — rendering them
 * in local time would show Sep 16 west of Greenwich. Empty for null/invalid.
 */
export function formatShortDate(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return '';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

/** "Sep 2026" (UTC). Empty for null/invalid. */
export function formatMonthYear(iso: string | null | undefined): string {
  const d = parseDate(iso);
  if (!d) return '';
  return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
}

/** "$0.46" — two decimals, the precision the header and footer show. */
export function formatUsd(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/**
 * The header's sub line after the fixed lead sentence:
 * "Last run Oct 7 at 01:31 UTC on server-laptop. $0.46 of the $5.00 budget used."
 * A run that did not end `ok` says so ("… (stopped)."); no runs at all reads
 * "No runs yet." The spend sentence is always present — it is the cap the loop
 * stops at, so it matters before the first run too.
 */
export function formatRunLine(stats: LaunchRadarStats): string {
  const spend = `${formatUsd(stats.spendUsd)} of the ${formatUsd(stats.capUsd)} budget used.`;
  const run = stats.lastRun;
  const started = parseDate(run?.startedAt);
  if (!run || !started) return `No runs yet. ${spend}`;
  const hh = String(started.getUTCHours()).padStart(2, '0');
  const mm = String(started.getUTCMinutes()).padStart(2, '0');
  const host = run.host ? ` on ${run.host}` : '';
  const state = run.status === 'ok' ? '' : ` (${run.status})`;
  return `Last run ${formatShortDate(run.startedAt)} at ${hh}:${mm} UTC${host}${state}. ${spend}`;
}

/**
 * Record over the closed provider union, so a new backend provider is a
 * compile error here rather than a raw key on the card.
 */
const ATS_LABEL: Record<LaunchRadarAtsProvider, string> = {
  greenhouse: 'Greenhouse',
  ashby: 'Ashby',
  lever: 'Lever',
  gem: 'Gem',
  workday: 'Workday',
  eightfold: 'Eightfold',
  other: 'Other',
  none: 'None',
};

export function atsLabel(provider: LaunchRadarAtsProvider): string {
  return ATS_LABEL[provider];
}

/**
 * The footer's left side: "Ashby board, 9 open jobs" when the free public API
 * verified the board, "Workday board, no PR" when the brief named a provider we
 * could not verify, else "No job board found".
 */
export function boardLine(ats: LaunchRadarAts): string {
  if (ats.verified && ats.provider !== 'none') {
    if (ats.jobCount == null) return `${atsLabel(ats.provider)} board`;
    const jobs = ats.jobCount === 1 ? '1 open job' : `${ats.jobCount} open jobs`;
    return `${atsLabel(ats.provider)} board, ${jobs}`;
  }
  if (ats.provider !== 'none') return `${atsLabel(ats.provider)} board, no PR`;
  return 'No job board found';
}

/** "techcrunch.com" from a URL (leading `www.` dropped); null if it does not parse. */
export function hostnameOf(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, '') || null;
  } catch {
    return null;
  }
}

/** "A", "A and B", "A, B and C" — the card's list style (no Oxford comma). */
export function joinWithAnd(items: readonly string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

/**
 * Up to `limit` names, then "and N more". When nothing is left over the last
 * two are joined with "and".
 */
export function listWithMore(items: readonly string[], limit: number): string {
  if (items.length <= limit) return joinWithAnd(items);
  return `${items.slice(0, limit).join(', ')} and ${items.length - limit} more`;
}

/**
 * "Amazon (2), Twitter, Ledgerline and 9 more" — the team tally. Highest count first
 * (stable for ties, so the Task's own order breaks them); a count is shown only
 * when it is above 1.
 */
export function summarizeTally(tallies: readonly LaunchRadarTally[], limit: number): string {
  const names = [...tallies]
    .sort((a, b) => b.count - a.count)
    .map((t) => (t.count > 1 ? `${t.name} (${t.count})` : t.name));
  return listWithMore(names, limit);
}

/**
 * One funding bullet, split so the card can bold the head:
 * `{ head: "Series A $35M", tail: ", Sep 2026. Led by CRV, with Lightspeed and Y Combinator" }`.
 * Without leads the investors stand alone ("Seed $15M. Lightspeed, Figma
 * Ventures, Vercel Ventures and 8 more"); others are capped at 3 + "and N more".
 */
export function roundLine(round: LaunchRadarRound): { head: string; tail: string } {
  const head = [round.stage ?? 'Round', round.amountUsd].filter(Boolean).join(' ');
  const when = formatMonthYear(round.announcedAt);
  const datePart = when ? `, ${when}` : '';
  const leads = round.leadInvestors;
  const others = round.otherInvestors;
  let investors = '';
  if (leads.length > 0) {
    investors = `Led by ${joinWithAnd(leads)}`;
    if (others.length > 0) investors += `, with ${listWithMore(others, 3)}`;
  } else if (others.length > 0) {
    investors = listWithMore(others, 3);
  }
  return { head, tail: `${datePart}.${investors ? ` ${investors}` : ''}` };
}
