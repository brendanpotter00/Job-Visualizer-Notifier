/**
 * Landing-page content config — the single source every prototype renders from.
 *
 * Every user-facing claim here traces to docs/seo/positioning-brief.md (§4–§8,
 * §10); the `evidence` field on each claim carries the breadcrumb. Editing copy
 * here updates all four prototypes at once — prototypes never hardcode claims.
 */
import { ROUTES } from '../../config/routes';

export type ClaimId =
  | 'straight_from_source'
  | 'minutes_after_posting'
  | 'no_reposts'
  | 'curated_companies'
  | 'thousands_weekly'
  | 'apply_early_rolling';

export interface LandingClaim {
  id: ClaimId;
  /** Short section heading. */
  heading: string;
  /** One- to two-sentence body. */
  body: string;
  /** Traceability breadcrumb to the positioning brief (not rendered). */
  evidence: string;
}

export type HeroVariantId = 'source' | 'antiNoise';

export interface HeroVariant {
  id: HeroVariantId;
  /** The single h1. Brief §9: query phrase + differentiator + a number. */
  headline: string;
  /** Fragment-stack subheadline (brief §11: 9–19 words, fragments not prose). */
  subheadline: string;
}

export interface LandingCta {
  label: string;
  to: string;
}

export interface LandingFaqEntry {
  question: string;
  /** Answer-first: the opening sentence must answer directly (brief §10 P2). */
  answer: string;
}

export interface LandingContent {
  productName: string;
  /**
   * Entity + category co-occurrence line (brief §10 P3) — rendered high on the
   * page and reused wherever a one-liner describes the product.
   */
  categoryLine: string;
  heroVariants: Record<HeroVariantId, HeroVariant>;
  /** SWE-flagship support line (brief §2). */
  broadSupportLine: string;
  /** The apply-early beat (brief §4) — supporting, never the hook. */
  supportingBeat: string;
  /**
   * Standalone liftable sentences (brief §10 P1) — rendered verbatim as a
   * quotable block; subject-verb-number, no surrounding context needed.
   */
  quotableClaims: readonly string[];
  claims: Record<ClaimId, LandingClaim>;
  /** Factual comparison beat (brief §10 P4). */
  comparison: string;
  /** Hero carries ONLY the primary (brief §11); secondary lives in nav/footer. */
  ctas: { primary: LandingCta; secondary: LandingCta };
  faq: readonly LandingFaqEntry[];
  /** Query-shaped internal link stubs (brief §9); targets are placeholders
   *  until 11.3 ships real category/company pages. */
  popularSearches: readonly LandingCta[];
  footer: { tagline: string; links: readonly LandingCta[] };
}

/**
 * Hand-picked household names for the fresh-jobs rail and live-activity stats
 * (brief §8 — Brendan edits). The broader logo wall draws from the full
 * COMPANIES registry; this list only decides who headlines.
 */
export const TOP_COMPANY_IDS: readonly string[] = [
  'apple',
  'google',
  'microsoft',
  'netflix',
  'spacex',
  'openai',
  'anthropic',
  'stripe',
  'databricks',
  'palantir',
  'robinhood',
  'reddit',
  'discord',
  'airbnb',
  'pinterest',
  'spotify',
  'roblox',
  'cloudflare',
  'waymo',
  'xai',
  'doordashusa',
  'instacart',
  'snowflake',
  'dropbox',
];

export const LANDING_CONTENT: LandingContent = {
  productName: 'onesecondswe',
  categoryLine:
    'onesecondswe is a free job board for software engineers that shows jobs the day they’re posted.',
  heroVariants: {
    source: {
      id: 'source',
      headline: 'Software engineer jobs, minutes after they’re posted.',
      subheadline:
        'Straight from 130+ company career pages. Median 45 minutes from company post to your feed.',
    },
    antiNoise: {
      id: 'antiNoise',
      headline: 'No reposts. No stale listings. No noise.',
      subheadline:
        'Job boards resurface months-old postings. We watch 130+ career pages and show what’s actually new.',
    },
  },
  broadSupportLine:
    'Software engineering first — plus product, data science, hardware, and growth roles from the same boards.',
  supportingBeat:
    'Recruiters review applications on a rolling basis. Apply in the first hours and a human actually reads your resume. onesecondswe exists so you’re early — every time.',
  quotableClaims: [
    'onesecondswe surfaces new software engineering jobs a median of 45 minutes after companies post them on their own career pages.',
    'onesecondswe scrapes 130+ curated tech companies’ career pages directly — no aggregator feeds, no reposts.',
    'Every posting date on onesecondswe is the moment we first saw the job on the company’s board, so “posted 2 hours ago” means exactly that.',
    'Thousands of new software engineering jobs are added every week, free.',
  ],
  claims: {
    straight_from_source: {
      id: 'straight_from_source',
      heading: 'Straight from the source',
      body: 'Every listing is scraped directly from the company’s own careers page — never from a reposted aggregator feed.',
      evidence: 'brief §5 straight_from_source (interview Q1)',
    },
    minutes_after_posting: {
      id: 'minutes_after_posting',
      heading: 'Minutes, not weeks',
      body: 'The median job here appears about 45 minutes after the company posts it, measured across tens of thousands of listings.',
      evidence: 'brief §5 minutes_after_posting (prod median 0.76h)',
    },
    no_reposts: {
      id: 'no_reposts',
      heading: 'Freshness you can trust',
      body: 'We timestamp the moment a job first appears on the company’s board. Reposts can’t fake it.',
      evidence: 'brief §5 no_reposts (first_seen_at design)',
    },
    curated_companies: {
      id: 'curated_companies',
      heading: '130+ curated companies',
      body: 'Hand-picked companies you’d actually want to work for — not a scrape of everything with a careers page.',
      evidence: 'brief §5 curated_companies (interview Q1/Q4)',
    },
    thousands_weekly: {
      id: 'thousands_weekly',
      heading: 'Thousands of new roles weekly',
      body: 'New listings stream in all week, every week — labeled by role and level so you can cut straight to yours.',
      evidence: 'brief §5 thousands_weekly (prod ~2.7k/7d)',
    },
    apply_early_rolling: {
      id: 'apply_early_rolling',
      heading: 'Early applications get read',
      body: 'Recruiters review on a rolling basis. The earlier you apply, the more likely a human sees your resume.',
      evidence: 'brief §5 apply_early_rolling (interview Q1/Q2)',
    },
  },
  comparison:
    'Unlike boards that syndicate and re-list jobs with reset dates, onesecondswe reads company career pages directly and never reposts.',
  ctas: {
    primary: { label: 'Browse jobs', to: ROUTES.RECENT_JOBS },
    secondary: { label: 'Create free account', to: ROUTES.ACCOUNT },
  },
  faq: [
    {
      question: 'Where can I find tech jobs the day they’re posted?',
      answer:
        'onesecondswe is a free job board for software engineers that scrapes 130+ tech companies’ career pages directly, so new roles appear a median of about 45 minutes after the company posts them — the same day, usually the same hour. Because it pulls from company boards rather than aggregator feeds, you see jobs before they syndicate elsewhere.',
    },
    {
      question: 'How fast do new jobs show up on onesecondswe?',
      answer:
        'A median of roughly 45 minutes after a company publishes the role on its own career page. onesecondswe continuously monitors 130+ company boards instead of waiting for jobs to be re-syndicated by aggregators.',
    },
    {
      question: 'Why do job postings on big boards look new but are actually old?',
      answer:
        'Aggregators re-syndicate listings and companies re-post roles, which resets the “posted” date without the job being new. onesecondswe never reposts: the date on every listing is when we first detected it on the employer’s own career page, so freshness is real, not recycled.',
    },
    {
      question: 'How does onesecondswe know a job’s real posting date?',
      answer:
        'Freshness on onesecondswe means the moment we first saw the job appear on the company’s career page. We check each of our 130+ tracked companies’ boards continuously and timestamp the first sighting — that timestamp is the posting date shown.',
    },
    {
      question: 'How many companies and jobs does onesecondswe cover?',
      answer:
        '130+ curated tech companies, tracked at the source, with thousands of new software engineering jobs added weekly — plus product, data science, hardware, and growth roles from the same boards.',
    },
    {
      question: 'Is onesecondswe free?',
      answer:
        'Yes. Browsing is free; a free account unlocks the full board, saved filters, and default time windows.',
    },
  ],
  popularSearches: [
    { label: 'SpaceX software engineer jobs', to: ROUTES.RECENT_JOBS },
    { label: 'New grad software engineer jobs 2026', to: ROUTES.RECENT_JOBS },
    { label: 'Software engineering internships', to: ROUTES.RECENT_JOBS },
    { label: 'Remote software engineer jobs', to: ROUTES.RECENT_JOBS },
    { label: 'Anthropic software engineer jobs', to: ROUTES.RECENT_JOBS },
    { label: 'Jobs posted today', to: ROUTES.RECENT_JOBS },
  ],
  footer: {
    tagline: '130+ companies. ~45 min median. Zero reposts.',
    links: [
      { label: 'Browse jobs', to: ROUTES.RECENT_JOBS },
      { label: 'Companies we track', to: ROUTES.CURATED_COMPANIES },
      { label: 'Why this was built', to: ROUTES.WHY },
      { label: 'Create free account', to: ROUTES.ACCOUNT },
    ],
  },
};
