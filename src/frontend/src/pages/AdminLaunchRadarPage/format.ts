// Pure formatting helpers for the Launch Radar admin page. No React here, so
// every sentence the cards print is unit tested in isolation
// (__tests__/pages/AdminLaunchRadarPage/format.test.ts).

import {
  DEFAULT_LAUNCH_RADAR_SORT,
  LAUNCH_RADAR_SORTS,
  type LaunchRadarAts,
  type LaunchRadarAtsProvider,
  type LaunchRadarRound,
  type LaunchRadarSort,
  type LaunchRadarStats,
  type LaunchRadarTally,
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

/** A month without a day: `2026-09`. */
const ISO_MONTH = /^\d{4}-\d{2}$/;

/**
 * An event's announcement date: "Sep 17", or "Sep 2026" when only the month is
 * known. The backend stores `YYYY-MM-DD` or `YYYY-MM`, and `Date` reads
 * `2026-09` as Sep 1, so a month-only date must not go through
 * `formatShortDate` (it would claim a day nobody reported).
 */
export function formatEventDate(iso: string | null | undefined): string {
  return iso && ISO_MONTH.test(iso) ? formatMonthYear(iso) : formatShortDate(iso);
}

/**
 * Notes the loop keeps in `issues` that say where data came from, not that
 * research fell short. The payload has no field for them, so they are told
 * apart by prefix (the loop may append a suffix such as "; 2 company page(s)
 * dropped"). `leaders from the brief` = FindAll confirmed nobody, so the
 * leaders are the company brief's founders.
 */
const LEADERS_FROM_BRIEF = 'leaders from the brief';
const PROVENANCE_PREFIXES: readonly string[] = [LEADERS_FROM_BRIEF];

/** The issues that are real research gaps: every provenance note left out. */
export function researchGaps(issues: readonly string[]): string[] {
  return issues.filter((issue) => !PROVENANCE_PREFIXES.some((p) => issue.startsWith(p)));
}

/** True when the card's leaders came from the company brief rather than the people search. */
export function leadersFromBrief(issues: readonly string[]): boolean {
  return issues.some((issue) => issue.startsWith(LEADERS_FROM_BRIEF));
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
 * verified the board, "Workday board, not verified" when the brief named a
 * provider we could not verify, else "No job board found".
 */
export function boardLine(ats: LaunchRadarAts): string {
  if (ats.verified && ats.provider !== 'none') {
    if (ats.jobCount == null) return `${atsLabel(ats.provider)} board`;
    const jobs = ats.jobCount === 1 ? '1 open job' : `${ats.jobCount} open jobs`;
    return `${atsLabel(ats.provider)} board, ${jobs}`;
  }
  if (ats.provider !== 'none') return `${atsLabel(ats.provider)} board, not verified`;
  return 'No job board found';
}

/**
 * The URL, normalized, when it is an absolute `http(s)` link; else null. The
 * gate between research data and EVERY `href` on a card (website, job board,
 * announcement): all of it comes from untrusted web data, so a `javascript:`
 * or `data:` URL must never become a link.
 */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null;
  }
}

/**
 * The card's "Job board" link: the ATS board when it is a safe `http(s)` URL,
 * else the careers page when that is; null when neither is (no link renders).
 */
export function jobBoardHref(ats: LaunchRadarAts, careersUrl: string | null): string | null {
  return safeHttpUrl(ats.boardUrl) ?? safeHttpUrl(careersUrl);
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

/**
 * The page URL's `?sort=` as a sort key. Absent, empty, a stale bookmark or a
 * typo all read as the default (newest announcement), never as an error.
 */
export function parseSort(raw: string | null): LaunchRadarSort {
  return LAUNCH_RADAR_SORTS.find((key) => key === raw) ?? DEFAULT_LAUNCH_RADAR_SORT;
}

/**
 * How loudly a score's numeral speaks. `normal` is the badge as it always
 * looks; sorting by one score makes that one `strong` (full-strength text) and
 * the other `muted` (secondary text).
 */
export type ScoreEmphasis = 'normal' | 'strong' | 'muted';

/** Talent and VC emphasis for the list's sort: only a score sort changes them. */
export function scoreEmphasis(sort: LaunchRadarSort): { talent: ScoreEmphasis; vc: ScoreEmphasis } {
  if (sort === 'talent') return { talent: 'strong', vc: 'muted' };
  if (sort === 'vc') return { talent: 'muted', vc: 'strong' };
  return { talent: 'normal', vc: 'normal' };
}

/**
 * The DOM id of a card's details toggle. The page moves focus to the next
 * card's toggle when a card leaves the list.
 */
export function cardToggleId(cardId: number): string {
  return `radar-card-${cardId}-toggle`;
}
