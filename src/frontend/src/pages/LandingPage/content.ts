/**
 * Landing-page content config — the single source the page renders from.
 *
 * Every user-facing claim here traces to docs/seo/positioning-brief.md (§4–§10)
 * or to a dated owner decision; the `evidence` field on each claim carries the
 * breadcrumb. Sections never hardcode claims, so copy edits happen here and
 * nowhere else.
 *
 * House style (owner-directed 2026-08-09 and 2026-09-10): periods and commas,
 * never em-dashes; as few words as the claim survives on. Every section opens
 * the same way, with one short heading, so the page reads as a column of quiet
 * blocks rather than prose. (The small uppercase eyebrow that used to sit over
 * each heading was cut on 2026-11-12, owner-directed.)
 */
import { ROUTES } from '../../config/routes';

export interface LandingCta {
  label: string;
  to: string;
}

export interface SectionIntro {
  heading: string;
}

export interface LandingHero {
  headline: string;
  evidence: string;
}

/**
 * One row of the LinkedIn comparison. Both cells are ≤ 8 words and both must be
 * checkable: the LinkedIn cell describes a product behaviour anyone can verify
 * on LinkedIn today (a repost button, promoted listings), never a judgement.
 */
export interface ComparisonRow {
  id: string;
  label: string;
  linkedin: string;
  onesecondswe: string;
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

export interface LandingFaqEntry {
  question: string;
  /** Answer-first: the opening sentence must answer directly (brief §10 P2). */
  answer: string;
}

/**
 * The landing header — the page's only chrome.
 * Deliberately no menu: a wordmark, three quiet nav links (Jobs, Companies,
 * Changelog — "Jobs" added 2026-11-12, owner-directed), and the two auth
 * actions. The header is wayfinding; the sections below do the selling, so a
 * fourth nav link (or a dropdown) is a content bug, not a layout choice. The
 * cap is enforced by the content test, not by convention.
 */
export interface LandingHeaderContent {
  wordmark: LandingCta;
  /** Quiet nav, desktop only (hidden at xs, where the bar is wordmark + Sign up). */
  nav: readonly LandingCta[];
  /** Text-button auth link. Hidden at xs so Sign up carries the phone bar alone. */
  logIn: LandingCta;
  /** Contained auth CTA — the only button that survives to the xs layout. */
  signUp: LandingCta;
  /**
   * The public repo. No longer rendered (the header's GitHub mark was cut on
   * 2026-11-12, owner-directed); kept because it is the Organization's
   * JSON-LD `sameAs`. External, so an absolute `href` rather than a `to`.
   */
  sourceCode: { label: string; href: string; evidence: string };
  /** Traceability breadcrumb (not rendered). */
  evidence: string;
}

export interface LandingSeoContent {
  title: string;
  description: string;
  siteUrl: string;
  canonicalPath: string;
  ogImagePath: string;
}

export interface LandingContent {
  productName: string;
  /**
   * Entity + category co-occurrence line (brief §10 P3) — the one sentence that
   * says what the product is. Feeds the head's JSON-LD `WebSite.description`;
   * no longer rendered on the page since the footer was cut (2026-11-12).
   */
  categoryLine: string;
  header: LandingHeaderContent;
  hero: LandingHero;
  ctas: { primary: LandingCta; secondary: LandingCta };
  freshJobs: SectionIntro;
  /**
   * The LinkedIn comparison. Naming LinkedIn in shipped copy was on the brief's
   * do-not-say list (§6) until the owner asked for exactly this section on
   * 2026-09-10; the override is recorded there and in
   * docs/marketing/business-context.md. Every row stays factual (brief §10 P4).
   */
  comparison: SectionIntro & {
    columns: { linkedin: string; onesecondswe: string };
    rows: readonly ComparisonRow[];
    evidence: string;
  };
  companies: SectionIntro;
  /**
   * The feature set as a skimmable matrix, in two tiers: `features` is live
   * today, `comingSoon` is not built yet and renders grayed out under
   * `comingSoonLabel`. The second tier exists by owner decision (2026-08-20,
   * recorded in docs/marketing/business-context.md), which carved a narrow
   * exception into the "nothing unshipped on the landing page" stance: an
   * unshipped capability may appear ONLY inside a clearly-labeled, visually
   * disabled tier. `nextUp` closes the section as the coda after the roadmap.
   *
   * A cell GRADUATES by moving arrays and rewriting its copy present-tense in
   * the same edit — `track_any_company` did on 2026-09-03. That is the only
   * sanctioned way across; the tier is the status, so a cell can never be
   * stale-by-flag in place.
   */
  featureMatrix: SectionIntro & {
    features: readonly LandingFeature[];
    /** Overline above the grayed tier. Must name the state, not imply it. */
    comingSoonLabel: string;
    comingSoon: readonly LandingFeature[];
    nextUp: LandingCta;
  };
  faq: SectionIntro & { entries: readonly LandingFaqEntry[] };
  closing: { heading: string; evidence: string };
  seo: LandingSeoContent;
}

/**
 * Hand-picked household names for the fresh-jobs rail (brief §8 — Brendan
 * edits). The broader logo wall draws from the full COMPANIES registry; this
 * list only decides who headlines.
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
    // "Changelog" points at the vote-features page because that page IS the
    // public changelog: shipped work moves out of the vote list into its
    // read-only "Shipped — built with the community" section. It replaced the
    // "Why" link on 2026-09-03 (owner-directed) — what shipped recently is a
    // better second link than the origin story.
    nav: [
      { label: 'Jobs', to: ROUTES.RECENT_JOBS },
      { label: 'Companies', to: ROUTES.CURATED_COMPANIES },
      { label: 'Changelog', to: ROUTES.VOTE_FEATURES },
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
  hero: {
    headline: 'No reposts. No stale listings. No noise. Just jobs.',
    evidence:
      'brief §4 B1 (owner favourite, 2026-08-09) plus "Just jobs." (owner-directed 2026-11-12, replacing the gray §9 continuation).',
  },
  ctas: {
    primary: { label: 'Browse jobs', to: ROUTES.RECENT_JOBS },
    secondary: { label: 'Create account', to: ROUTES.ACCOUNT },
  },
  freshJobs: {
    heading: 'Just posted',
  },
  comparison: {
    heading: 'Built for the candidate',
    columns: { linkedin: 'LinkedIn', onesecondswe: 'onesecondswe' },
    rows: [
      {
        id: 'reposts',
        label: 'Reposts',
        linkedin: 'Reposts add noise to your feed.',
        onesecondswe: 'Never. Real dates.',
        evidence:
          'brief §3 theme 1 + §5 no_reposts (first_seen_at design); LinkedIn "Repost job" creates a new posting with a new date.',
      },
      {
        id: 'companies',
        label: 'Companies',
        linkedin: 'Companies you don’t care about.',
        onesecondswe: '130+ hand-picked companies.',
        evidence: 'brief §5 curated_companies (interview Q1/Q4)',
      },
      {
        id: 'ranking',
        label: 'Ranking',
        linkedin: 'Paid listings first.',
        onesecondswe: 'Newest. Filtered. Curated.',
        evidence:
          'business-context §core positioning (no repost mechanism exists and none will be sold); LinkedIn Promoted Jobs is a paid placement product. Board sorts by first_seen desc.',
      },
      {
        id: 'source',
        label: 'Source',
        linkedin: 'Re-listed feeds.',
        onesecondswe: 'Straight from career pages.',
        evidence: 'brief §5 straight_from_source + §10 P4 comparison framing',
      },
    ],
    evidence:
      'owner-directed 2026-09-10: "a section on why it is better than linkedin, like there are no reposts and the companies are already curated". Overrides brief §6 (LinkedIn by name); recorded there.',
  },
  companies: {
    heading: 'Curated companies',
  },
  featureMatrix: {
    heading: 'What you get',
    features: [
      {
        id: 'freshness',
        name: 'Seconds, not weeks',
        detail: 'Jobs minutes after posting.',
        evidence:
          'brief §5 minutes_after_posting (prod median 0.76h). Was "Seconds, not weeks" (owner-directed 2026-08-09); reworded 2026-09-10 when the proof strip put the 45-minute median in a headline two sections away, so the page states ONE freshness number. Reverting is a one-word edit if the owner prefers "seconds".',
      },
      {
        id: 'ai_labels',
        name: 'AI-labeled roles',
        detail: 'Level, category, location.',
        evidence: 'business-context §feature-set: AI-powered labeling, LIVE today',
      },
      {
        id: 'saved_filters',
        name: 'Saved filters',
        detail: 'Set once. Filtered forever.',
        evidence: 'business-context §feature-set: saved filters, LIVE today',
      },
      {
        id: 'track_any_company',
        name: 'Track any company',
        detail: 'Name it. We watch it.',
        evidence:
          'EPIC Custom company sources wdwb1cbnc2; SHIPPED on main 2026-09-02, graduated out of the coming-soon tier 2026-09-03. Rollout is flag-gated (VITE_CUSTOM_COMPANIES_ENABLED + backend CUSTOM_COMPANY_SOURCES_ENABLED), so the claim is true where the flags are on.',
      },
      {
        id: 'reach_recruiter',
        name: 'Reach the recruiter',
        detail: 'One click to the hiring team.',
        evidence:
          'owner-directed 2026-08-09, backed by the job card’s LinkedIn people-search link. Moved out of the apply-early closer 2026-09-10 so that line could shrink.',
      },
      {
        id: 'free',
        name: 'Free',
        detail: 'Browse and sign up free.',
        evidence: 'brief §10 P1 (“added every week, free”); FAQ “Is onesecondswe free?”',
      },
    ],
    comingSoonLabel: 'Coming soon',
    comingSoon: [
      {
        id: 'mcp_access',
        name: 'MCP',
        detail: 'Build your own integrations.',
        evidence: 'EPIC Power-user data access (replica + MCP), wdwb1cbnce',
      },
      {
        id: 'ai_notifications',
        name: 'AI notifications',
        detail: 'Alerts on jobs that fit you. No noise.',
        evidence: 'EPIC Notifications wdwb1cbncb + 12.1/15.9; resume-rubric per Brendan 2026-08-20',
      },
    ],
    nextUp: {
      label: 'Built with community. Vote.',
      to: ROUTES.VOTE_FEATURES,
    },
  },
  faq: {
    heading: 'FAQ',
    entries: [
      {
        question: 'Is onesecondswe free?',
        answer: 'Yes. Browsing and accounts are free.',
      },
      {
        question: 'Why do old jobs look new on big boards?',
        answer:
          'Companies pay to repost or sponsor their jobs and clutter your feed. onesecondswe dates every job when it first appears on the company’s own career page.',
      },
      {
        question: 'How fast do jobs show up on onesecondswe?',
        answer: 'About 45 minutes after a company posts, on median. onesecondswe watches career pages.',
      },
      {
        question: 'How is onesecondswe different from LinkedIn?',
        answer:
          'onesecondswe reads career pages directly and never reposts, so every date is real. LinkedIn lets companies repost with a fresh date and ranks paid listings first.',
      },
    ],
  },
  closing: {
    heading: 'Be early',
    evidence: 'brief §4 supporting beat ("onesecondswe exists so you’re early, every time")',
  },
  seo: {
    title: 'Software Engineer Jobs, Minutes After They’re Posted | onesecondswe',
    description:
      'A free job board for software engineers. Jobs straight from 130+ curated company career pages, a median of 45 minutes after posting. No reposts, no noise.',
    siteUrl: 'https://onesecondswe.dev',
    canonicalPath: ROUTES.HOME,
    ogImagePath: '/og-image.png',
  },
};
