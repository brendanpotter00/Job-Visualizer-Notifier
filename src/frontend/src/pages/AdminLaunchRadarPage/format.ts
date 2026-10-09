// Pure formatting helpers for the Launch Radar admin page. No React here, so
// every sentence the cards print is unit tested in isolation
// (__tests__/pages/AdminLaunchRadarPage/format.test.ts).

import {
  DEFAULT_LAUNCH_RADAR_SORT,
  LAUNCH_RADAR_SORTS,
  type LaunchRadarAts,
  type LaunchRadarAtsProvider,
  type LaunchRadarCard,
  type LaunchRadarRound,
  type LaunchRadarScores,
  type LaunchRadarSort,
  type LaunchRadarSource,
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

/** "$0.46" — two decimals, the precision the card footer shows. */
export function formatUsd(amount: number): string {
  return `$${amount.toFixed(2)}`;
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

/**
 * A pull request of this repository, nothing else (no fragment, no query, no
 * trailing path). A SEAM: the same pattern as the backend's DB CHECK and
 * `LAUNCH_RADAR_PR_URL_RE` (models.py), `pr_queue.py` and `pr_step.py`
 * (CONTRACT §9). The backend never sends another URL; this is the last gate.
 */
const PR_URL_RE = /^https:\/\/github\.com\/brendanpotter00\/Job-Visualizer-Notifier\/pull\/(\d+)$/;

/**
 * The card's "View PR #N" link: its add-company PR when the URL is exactly a
 * pull request of this repository (and so a safe `https` URL); else null (no
 * link renders).
 */
export function prHref(card: Pick<LaunchRadarCard, 'prUrl'>): string | null {
  const url = card.prUrl;
  return url && PR_URL_RE.test(url) ? safeHttpUrl(url) : null;
}

/**
 * "View PR #123", or null when `prHref` is null. The number is read from the
 * URL the link opens, so the label can never name a different PR than the
 * link (the backend derives `prNumber` from the same URL).
 */
export function prLabel(card: Pick<LaunchRadarCard, 'prUrl'>): string | null {
  const match = PR_URL_RE.exec(card.prUrl ?? '');
  return match ? `View PR #${match[1]}` : null;
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

// ---- Sources

/** The topics a card's sources are grouped by. */
export type SourceTopic = 'company' | 'funding' | 'people';

/** Group order on the card, and each group's visible label. */
const SOURCE_TOPICS: readonly { topic: SourceTopic; label: string }[] = [
  { topic: 'company', label: 'Company' },
  { topic: 'funding', label: 'Funding' },
  { topic: 'people', label: 'People' },
];

/**
 * Every output field a citation can support, by its top-level name, with what
 * it backs up in plain words. Sources: the company brief, each leader's
 * pedigree, the FindAll leader match condition (scripts/launch_radar/schemas.py,
 * leaders.py). A Map, so a field named like an Object.prototype key is unknown.
 */
const SOURCE_FIELDS = new Map<string, { topic: SourceTopic; label: string }>([
  // The company brief.
  ['one_liner', { topic: 'company', label: 'one-liner' }],
  ['website_url', { topic: 'company', label: 'website' }],
  ['what_they_do', { topic: 'company', label: 'what they do' }],
  ['notable_facts', { topic: 'company', label: 'highlights' }],
  ['blurb', { topic: 'company', label: 'description' }],
  ['careers_url', { topic: 'company', label: 'careers page' }],
  ['ats', { topic: 'company', label: 'job board' }],
  // The brief's funding fields.
  ['latest_round', { topic: 'funding', label: 'latest round' }],
  ['prior_rounds', { topic: 'funding', label: 'earlier rounds' }],
  ['total_raised_usd', { topic: 'funding', label: 'total raised' }],
  ['latest_announcement', { topic: 'funding', label: 'announcement' }],
  // The brief's founders, each leader's pedigree, and the FindAll match condition.
  ['founders', { topic: 'people', label: 'founders' }],
  ['current_title', { topic: 'people', label: 'current title' }],
  ['linkedin_url', { topic: 'people', label: 'LinkedIn profile' }],
  ['education', { topic: 'people', label: 'education' }],
  ['prior_roles', { topic: 'people', label: 'past roles' }],
  ['founded_before', { topic: 'people', label: 'companies founded before' }],
  ['years_experience', { topic: 'people', label: 'years of experience' }],
  ['industry_experience_summary', { topic: 'people', label: 'industry experience' }],
  ['notable_signals', { topic: 'people', label: 'notable work' }],
  ['current_leader_at_company', { topic: 'people', label: 'current leadership role' }],
]);

/**
 * What one citation supports: its topic and, in plain words, the field. The
 * field is read up to its first dot (`prior_rounds.0` is `prior_rounds`), as
 * the loop does. An unknown field is Company, labelled with its name in words
 * (`mystery_field` is "mystery field"). A null field, or one that does not start
 * with a letter, is Company with no label.
 */
export function sourceField(field: string | null): { topic: SourceTopic; label: string | null } {
  const base = field?.split('.')[0] ?? '';
  const known = SOURCE_FIELDS.get(base);
  if (known) return { ...known };
  return { topic: 'company', label: /^[a-z]/i.test(base) ? base.replace(/_/g, ' ') : null };
}

/** One source as the card lists it. */
export interface SourceLink {
  /** The source URL, normalized; only http(s) URLs get here. */
  href: string;
  /** The link text: the citation's title, or the site when it has none. */
  text: string;
  /**
   * "techcrunch.com · latest round". The site is left out when it is already the
   * link text. Null when there is neither a site to add nor a label.
   */
  detail: string | null;
}

export interface SourceGroup {
  topic: SourceTopic;
  /** "Company", "Funding" or "People". */
  label: string;
  items: SourceLink[];
}

/**
 * The card's sources grouped by topic: Company, Funding, People, in that order,
 * with empty groups left out. Within a group, the loop's order is kept (brief,
 * then each leader's pedigree, then FindAll), so one leader's sources sit
 * together. Only http(s) URLs are kept (`safeHttpUrl`). A URL that repeats once
 * normalized is dropped (the first wins). A blank title counts as missing.
 */
export function groupSources(sources: readonly LaunchRadarSource[]): SourceGroup[] {
  const byTopic = new Map<SourceTopic, SourceLink[]>();
  const seen = new Set<string>();
  for (const source of sources) {
    const href = safeHttpUrl(source.url);
    if (!href || seen.has(href)) continue;
    seen.add(href);
    const site = hostnameOf(href) ?? href;
    const title = source.title?.trim() || null;
    const { topic, label } = sourceField(source.field);
    const detail = [title ? site : null, label].filter((p): p is string => !!p).join(' · ') || null;
    const items = byTopic.get(topic) ?? [];
    items.push({ href, text: title ?? site, detail });
    byTopic.set(topic, items);
  }
  return SOURCE_TOPICS.flatMap(({ topic, label }) => {
    const items = byTopic.get(topic);
    return items ? [{ topic, label, items }] : [];
  });
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

/** The most each half of the Talent blend (the leaders, the rest of the team) can add. */
export const TALENT_PART_MAX = 50;

/** "Why these scores": the Talent bullet and, for a blended card, its two parts. */
export interface TalentBreakdown {
  line: string;
  /** `Leaders …` then `Team …`; empty for an unscored or legacy card. */
  parts: string[];
}

/** "Leaders 37: reasons", or "Team: why there is no team part" for a missing one. */
function talentPart(
  label: string,
  value: number | null,
  reasons: readonly string[],
  scoredWithoutReasons: string
): string {
  if (value == null)
    return `${label}: ${reasons.length > 0 ? reasons.join('; ') : 'no people data'}`;
  return `${label} ${value}: ${reasons.length > 0 ? reasons.join('; ') : scoredWithoutReasons}`;
}

/**
 * The Talent bullet of "Why these scores". An AI-graded card (§6.6.1) shows the
 * grade's four parts, its reasons and the rule-based score it replaced. Otherwise
 * Talent is a 50/50 blend (CONTRACT §6.6): "Talent 74: leaders 37 + team 37 (each out of 50)", or a lone part
 * doubled ("Talent 38: leaders 19 of 50, doubled: no team data"), with one
 * sub-bullet per part. A legacy card (no `talentBasis`, scored before the blend)
 * keeps the one line it always had; so does an unscored card.
 */
export function talentBreakdown(scores: LaunchRadarScores, incomplete: boolean): TalentBreakdown {
  const { talent, talentBasis: basis, talentAi: ai } = scores;
  if (ai != null && talent != null) {
    const p = ai.parts;
    return {
      line: `Talent ${talent}: AI grade, ${ai.confidence} confidence, judged as ${ai.industry}`,
      parts: [
        `Leaders ${p.leaders}/40 · industry fit ${p.industry}/25 · team ${p.team}/25 · track record ${p.trackRecord}/10`,
        ...ai.reasons,
        `Rule-based score: ${scores.talentRules ?? 'none (no people data)'}`,
      ],
    };
  }
  if (talent == null) {
    return {
      line: incomplete
        ? 'Talent: not scored, research incomplete'
        : 'Talent: no people data, so no score',
      parts: [],
    };
  }
  if (basis == null)
    return { line: `Talent ${talent}: ${scores.talentReasons.join('; ')}`, parts: [] };
  const leaders = talentPart(
    'Leaders',
    scores.talentLeaders,
    scores.talentReasons,
    'no top school, top employer, exit or 10+ years'
  );
  const team = talentPart(
    'Team',
    scores.talentTeam,
    scores.talentTeamReasons,
    'nothing the rubric counts'
  );
  let line: string;
  if (basis === 'both') {
    line = `Talent ${talent}: leaders ${scores.talentLeaders} + team ${scores.talentTeam} (each out of ${TALENT_PART_MAX})`;
  } else if (basis === 'leaders') {
    line = `Talent ${talent}: leaders ${scores.talentLeaders} of ${TALENT_PART_MAX}, doubled: no team data`;
  } else {
    line = `Talent ${talent}: team ${scores.talentTeam} of ${TALENT_PART_MAX}, doubled: no leader data`;
  }
  return { line, parts: [leaders, team] };
}

/**
 * The page URL's `?sort=` as a sort key. Absent, empty, a stale bookmark (such
 * as the retired `announced`) or a typo all read as the default (highest Talent),
 * never as an error.
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
