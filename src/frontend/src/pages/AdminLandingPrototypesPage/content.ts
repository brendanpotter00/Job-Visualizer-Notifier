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

/**
 * One mechanism step in the "How it works" section. Deliberately two fields and
 * no more: the label is the skim target, the line is the whole explanation.
 * If a step ever needs a paragraph, the step is wrong — not the type.
 */
export interface HowItWorksStep {
  id: string;
  /** 2–4 words, verb-first and parallel across steps. */
  label: string;
  /** ONE short line (≤ ~14 words). Never a second paragraph. */
  line: string;
  /** Traceability breadcrumb (not rendered). */
  evidence: string;
}

/**
 * A cell in the feature matrix. The same shape serves both tiers, and the TIER
 * is the array a cell lives in (`features` = live today, `comingSoon` = not
 * built yet) rather than a per-cell `status` field: a status flag invites a
 * third value and a cell that quietly changes tier without its copy changing
 * tense. Coming-soon copy is written future-tense or capability-neutral, so a
 * cell literally cannot read as shipped even if it were moved by mistake.
 */
export interface LandingFeature {
  id: string;
  /** 2–4 words — the only thing a skimming eye is guaranteed to read. */
  name: string;
  /** ≤ 8 words. Supporting detail, never a sentence with a subordinate clause. */
  detail: string;
  /** Traceability breadcrumb (not rendered). */
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

/**
 * The landing header — the one piece of page chrome all four prototypes share.
 * Deliberately four slots and no menu: a wordmark, two quiet nav links, and the
 * two auth actions. The header is wayfinding; the sections below do the selling,
 * so a third nav link (or a dropdown) is a content bug, not a layout choice. The
 * two-link cap is enforced by the content test, not by convention.
 */
export interface LandingHeaderContent {
  /** Plain-text wordmark, top-left. No logo image — the product name IS the mark. */
  wordmark: LandingCta;
  /** Quiet nav, desktop only (hidden at xs, where the bar is wordmark + Sign up). */
  nav: readonly LandingCta[];
  /** Text-button auth link. Hidden at xs so Sign up carries the phone bar alone. */
  logIn: LandingCta;
  /** Contained auth CTA — the only button that survives to the xs layout. */
  signUp: LandingCta;
  /**
   * Source-code mark on the right. External, so it carries an absolute `href`
   * rather than a `to` (nothing in ROUTES can describe it).
   */
  sourceCode: { label: string; href: string; evidence: string };
  /** Traceability breadcrumb (not rendered). */
  evidence: string;
}

export interface LandingContent {
  productName: string;
  /**
   * Entity + category co-occurrence line (brief §10 P3) — rendered high on the
   * page and reused wherever a one-liner describes the product.
   */
  categoryLine: string;
  /** The sticky top bar every prototype opens with. */
  header: LandingHeaderContent;
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
  /**
   * Mechanism, in three steps. Rendered as one section together with the
   * apply-early beat (`claims.apply_early_rolling.body`) — the "how" and the
   * "why you should care" belong to the same breath.
   */
  howItWorks: { heading: string; steps: readonly HowItWorksStep[] };
  /**
   * The feature set as a skimmable matrix, in two tiers: `features` is live
   * today, `comingSoon` is not built yet and renders grayed out under
   * `comingSoonLabel`. The second tier exists by owner decision (2026-08-20,
   * recorded in docs/marketing/business-context.md), which carved a narrow
   * exception into the "nothing unshipped on the landing page" stance: an
   * unshipped capability may appear ONLY inside a clearly-labeled, visually
   * disabled tier. `nextUp` still closes the section, now reading as the coda
   * after the roadmap rather than the whole answer to "what's next".
   */
  featureMatrix: {
    heading: string;
    features: readonly LandingFeature[];
    /** Overline above the grayed tier. Must name the state, not imply it. */
    comingSoonLabel: string;
    comingSoon: readonly LandingFeature[];
    nextUp: LandingCta;
  };
  /** Factual comparison beat (brief §10 P4). */
  comparison: string;
  /** Primary = browse (contained); secondary = create account (outlined). Both
   *  render in the heroes and in the closing CTA block. */
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
  header: {
    wordmark: { label: 'onesecondswe', to: ROUTES.RECENT_JOBS },
    nav: [
      { label: 'Companies', to: ROUTES.CURATED_COMPANIES },
      { label: 'Why', to: ROUTES.WHY },
    ],
    logIn: { label: 'Log in', to: ROUTES.ACCOUNT },
    signUp: { label: 'Sign up', to: ROUTES.ACCOUNT },
    sourceCode: {
      label: 'Source code',
      href: 'https://github.com/brendanpotter00/Job-Visualizer-Notifier',
      evidence: 'owner-suggested 2026-08-20, mock ok while repo private',
    },
    evidence:
      'owner-directed 2026-08-20 (a normal header: wordmark left, Log in / Sign up right). Both auth targets are the mock ACCOUNT route the hero CTAs already use; real Auth0 wiring is promotion-time work.',
  },
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
        'A job board built for candidates. Less time spent job hunting, more time for everything else.',
    },
  },
  broadSupportLine:
    'Software engineering first, plus product, data science, hardware, and growth roles from the same boards.',
  supportingBeat:
    'Recruiters review applications on a rolling basis. Apply in the first hours and a human actually reads your resume. onesecondswe exists so you’re early, every time.',
  quotableClaims: [
    'onesecondswe surfaces new software engineering jobs a median of 45 minutes after companies post them on their own career pages.',
    'onesecondswe scrapes 130+ curated tech companies’ career pages directly. No aggregator feeds, no reposts.',
    'Every posting date on onesecondswe is the moment we first saw the job on the company’s board, so “posted 2 hours ago” means exactly that.',
    'Thousands of new software engineering jobs are added every week, free.',
  ],
  claims: {
    straight_from_source: {
      id: 'straight_from_source',
      heading: 'Straight from the source',
      body: 'Every listing is scraped directly from the company’s own careers page, never from a reposted aggregator feed.',
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
      body: 'Hand-picked companies you’d actually want to work for, not a scrape of everything with a careers page.',
      evidence: 'brief §5 curated_companies (interview Q1/Q4)',
    },
    thousands_weekly: {
      id: 'thousands_weekly',
      heading: 'Thousands of new roles weekly',
      body: 'New listings stream in all week, every week, labeled by role and level so you can cut straight to yours.',
      evidence: 'brief §5 thousands_weekly (prod ~2.7k/7d)',
    },
    apply_early_rolling: {
      id: 'apply_early_rolling',
      heading: 'Early applications get read',
      body: 'Recruiters review on a rolling basis. The earlier you apply, the more likely a human sees your resume. Every job here links straight to the hiring managers and recruiters posting about it on LinkedIn, so you can message them within minutes of the role going up.',
      evidence:
        'brief §5 apply_early_rolling (interview Q1/Q2); second sentence owner-directed 2026-08-09, backed by the job card’s LinkedIn people-search link',
    },
  },
  howItWorks: {
    heading: 'How it works',
    steps: [
      {
        id: 'monitor',
        label: 'Monitor job boards',
        line: 'We watch 130+ curated companies’ career pages continuously.',
        evidence: 'brief §5 straight_from_source + curated_companies',
      },
      {
        id: 'label',
        label: 'Label every role',
        line: 'AI tags level, category, and location so filters actually mean something.',
        evidence: 'business-context §feature-set: AI-powered labeling, LIVE today',
      },
      {
        id: 'filters',
        label: 'Set up custom filters',
        line: 'Save your filters once and they apply on every visit, so you search less.',
        evidence: 'business-context §feature-set: saved filters, LIVE today',
      },
    ],
  },
  featureMatrix: {
    heading: 'Features',
    features: [
      {
        id: 'source',
        name: 'Straight from the source',
        detail: 'Scraped from company career pages.',
        evidence: 'brief §5 straight_from_source',
      },
      {
        id: 'freshness',
        name: 'Seconds, not weeks',
        detail: 'New roles land here seconds after posting.',
        evidence:
          'owner-directed 2026-08-09 (overrides ~45-min median claim; revisit before promotion)',
      },
      {
        id: 'ai_labels',
        name: 'AI-labeled roles',
        detail: 'Level, category, and location on every job.',
        evidence: 'business-context §feature-set: AI-powered labeling, LIVE today',
      },
      {
        id: 'curated',
        name: '130+ curated companies',
        detail: 'Hand-picked, not a scrape of everything.',
        evidence: 'brief §5 curated_companies',
      },
      {
        id: 'saved_filters',
        name: 'Saved filters',
        detail: 'Your searches, ready on every visit.',
        evidence: 'business-context §feature-set: saved filters, LIVE today',
      },
      {
        id: 'free',
        name: 'Free',
        detail: 'Free to browse, free to sign up.',
        evidence: 'brief §10 P1 (“added every week, free”); FAQ “Is onesecondswe free?”',
      },
    ],
    comingSoonLabel: 'Coming soon',
    comingSoon: [
      {
        id: 'mcp_access',
        name: 'Bring your AI',
        detail: 'MCP access from Claude or any agent.',
        evidence: 'EPIC Power-user data access (replica + MCP), wdwb1cbnce',
      },
      {
        id: 'ai_notifications',
        name: 'AI notifications',
        detail: 'Your resume and rubric, alerts on matches.',
        evidence: 'EPIC Notifications wdwb1cbncb + 12.1/15.9; resume-rubric per Brendan 2026-08-20',
      },
      {
        id: 'track_any_company',
        name: 'Track any company',
        detail: 'Name a company, we will build the scraper.',
        evidence: 'EPIC Custom company sources wdwb1cbnc2 (in flight)',
      },
    ],
    nextUp: {
      label: 'Built with the community. Vote on what’s next.',
      to: ROUTES.VOTE_FEATURES,
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
        'onesecondswe is a free job board for software engineers that scrapes 130+ tech companies’ career pages directly, so new roles appear a median of about 45 minutes after the company posts them, the same day and usually the same hour. Because it pulls from company boards rather than aggregator feeds, you see jobs before they syndicate elsewhere.',
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
        'Freshness on onesecondswe means the moment we first saw the job appear on the company’s career page. We check each of our 130+ tracked companies’ boards continuously and timestamp the first sighting, and that timestamp is the posting date shown.',
    },
    {
      question: 'How many companies and jobs does onesecondswe cover?',
      answer:
        '130+ curated tech companies, tracked at the source, with thousands of new software engineering jobs added weekly, plus product, data science, hardware, and growth roles from the same boards.',
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
