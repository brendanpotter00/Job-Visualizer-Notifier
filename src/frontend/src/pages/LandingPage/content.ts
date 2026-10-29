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
 * the same way, a tiny eyebrow over a short heading, so the page reads as a
 * column of quiet blocks rather than prose.
 */
import { ROUTES } from '../../config/routes';

export interface LandingCta {
  label: string;
  to: string;
}

/**
 * The opening every section shares. The eyebrow names the section (it never
 * sells), and the heading is the one line a skimming eye is guaranteed to read.
 */
export interface SectionIntro {
  /** ≤ 3 words, rendered as a small uppercase overline. */
  eyebrow: string;
  /** ≤ 8 words. */
  heading: string;
}

/**
 * The single h1, in two tones. `headline` is the black half (the anti-noise
 * hook, brief §4 B1). `continuation` is the gray half of the SAME h1, which is
 * where the query phrase and the number live (brief §9: "query phrase +
 * differentiator + a number"). Splitting the tones lets the hook stay four
 * words without the h1 losing its search phrase.
 */
export interface LandingHero {
  headline: string;
  continuation: string;
  /** Traceability breadcrumb (not rendered). */
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
 * One row of the LinkedIn comparison. Both cells are ≤ 8 words and both must be
 * checkable: the LinkedIn cell describes a product behaviour anyone can verify
 * on LinkedIn today (a repost button, promoted listings), never a judgement.
 */
export interface ComparisonRow {
  id: string;
  /** ≤ 3 words. */
  label: string;
  linkedin: string;
  onesecondswe: string;
  /** Traceability breadcrumb (not rendered). */
  evidence: string;
}

/**
 * One tile in the proof strip: the number big, and under it the standalone
 * subject-verb-number sentence (brief §10 P1) an answer engine can lift without
 * context. The sentence is the quotable claim; the value is its skim target.
 */
export interface ProofStat {
  id: string;
  value: string;
  sentence: string;
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

/**
 * What the document head says about the page (title, description, canonical,
 * social card). Rendered by `LandingSeo`, and repeated into the JSON-LD there,
 * so the entity + category line (brief §10 P3) reaches crawlers three ways.
 */
export interface LandingSeoContent {
  /** Brief §9 title shape: keyword-first + freshness cue + brand suffix. */
  title: string;
  /** ≤ 160 characters, answer-first. */
  description: string;
  /** Absolute origin, no trailing slash. */
  siteUrl: string;
  /** Path of the canonical URL for this page. */
  canonicalPath: string;
  /** Path of the social-card image (1200×630), served from `public/`. */
  ogImagePath: string;
}

export interface LandingContent {
  productName: string;
  /**
   * Entity + category co-occurrence line (brief §10 P3) — the one sentence that
   * says what the product is. Rendered in the footer and reused in the head.
   */
  categoryLine: string;
  /** The sticky top bar the page opens with. */
  header: LandingHeaderContent;
  hero: LandingHero;
  /** Primary = browse (contained); secondary = create account. Both render in
   *  the hero and again in the closing block. */
  ctas: { primary: LandingCta; secondary: LandingCta };
  /** Overline + heading above the three live job cards. */
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
    /** Traceability breadcrumb (not rendered). */
    evidence: string;
  };
  /**
   * Mechanism, in three steps, closed by the apply-early beat (brief §4) — the
   * "how" and the "why you should care" belong to the same breath.
   */
  howItWorks: SectionIntro & {
    steps: readonly HowItWorksStep[];
    closer: { line: string; evidence: string };
  };
  /** The quotable numbers (brief §10 P1), three tiles. */
  proof: SectionIntro & { stats: readonly ProofStat[] };
  /** Overline + heading above the curated-category grid. */
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
  /** The last line before the footer, over the same two CTAs as the hero. */
  closing: { heading: string; evidence: string };
  /** Footer nav only. */
  footer: { links: readonly LandingCta[] };
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
    // better second link than the origin story, and the footer still carries
    // "Why this was built" for anyone who wants it.
    nav: [
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
    headline: 'No reposts. No stale listings. No noise.',
    continuation:
      'Software engineer jobs from 130+ curated career pages, minutes after they’re posted.',
    evidence:
      'headline: brief §4 B1 (owner favourite, 2026-08-09). continuation: brief §9 h1 shape (query phrase + differentiator + a number) and §5 curated_companies / minutes_after_posting.',
  },
  ctas: {
    primary: { label: 'Browse jobs', to: ROUTES.RECENT_JOBS },
    secondary: { label: 'Create free account', to: ROUTES.ACCOUNT },
  },
  freshJobs: {
    eyebrow: 'Fresh jobs',
    heading: 'What just went up.',
  },
  comparison: {
    eyebrow: 'Why not LinkedIn',
    heading: 'Built for the candidate, not the repost.',
    columns: { linkedin: 'LinkedIn', onesecondswe: 'onesecondswe' },
    rows: [
      {
        id: 'reposts',
        label: 'Reposts',
        linkedin: 'Reposting an old job resets its date.',
        onesecondswe: 'Never. Dates are when we first saw them.',
        evidence:
          'brief §3 theme 1 + §5 no_reposts (first_seen_at design); LinkedIn "Repost job" creates a new posting with a new date.',
      },
      {
        id: 'companies',
        label: 'Companies',
        linkedin: 'Anyone can post a job.',
        onesecondswe: '130+ hand-picked companies, tracked at the source.',
        evidence: 'brief §5 curated_companies (interview Q1/Q4)',
      },
      {
        id: 'ranking',
        label: 'Ranking',
        linkedin: 'Promoted listings rank first.',
        onesecondswe: 'Newest first. No paid placement, ever.',
        evidence:
          'business-context §core positioning (no repost mechanism exists and none will be sold); LinkedIn Promoted Jobs is a paid placement product. Board sorts by first_seen desc.',
      },
      {
        id: 'source',
        label: 'Source',
        linkedin: 'Syndicated and re-listed feeds.',
        onesecondswe: 'Read directly from each careers page.',
        evidence: 'brief §5 straight_from_source + §10 P4 comparison framing',
      },
    ],
    evidence:
      'owner-directed 2026-09-10: "a section on why it is better than linkedin, like there are no reposts and the companies are already curated". Overrides brief §6 (LinkedIn by name); recorded there.',
  },
  howItWorks: {
    eyebrow: 'How it works',
    heading: 'Three steps. No middleman.',
    steps: [
      {
        id: 'monitor',
        label: 'Watch career pages',
        line: 'We check 130+ company boards around the clock.',
        evidence: 'brief §5 straight_from_source + curated_companies',
      },
      {
        id: 'label',
        label: 'Label every role',
        line: 'AI tags level, category, and location, so filters mean something.',
        evidence: 'business-context §feature-set: AI-powered labeling, LIVE today',
      },
      {
        id: 'filters',
        label: 'Set your filters',
        line: 'Save them once. They apply on every visit.',
        evidence: 'business-context §feature-set: saved filters, LIVE today',
      },
    ],
    closer: {
      line: 'Recruiters review on a rolling basis. Apply in the first hours and a human reads your resume.',
      evidence: 'brief §4 supporting beat + §5 apply_early_rolling (interview Q1/Q2)',
    },
  },
  proof: {
    eyebrow: 'By the numbers',
    heading: 'Measured, not promised.',
    stats: [
      {
        id: 'median',
        value: '45 min',
        sentence:
          'onesecondswe surfaces new jobs a median of 45 minutes after companies post them on their own career pages.',
        evidence: 'brief §1 (prod median 0.76h, 2026-07-25 → 2026-08-09) + §10 P1',
      },
      {
        id: 'companies',
        value: '130+',
        sentence: 'onesecondswe tracks 130+ curated tech companies’ career pages directly. No aggregator feeds.',
        evidence: 'brief §5 curated_companies + §10 P1',
      },
      {
        id: 'weekly',
        value: 'Thousands',
        sentence: 'Thousands of new software engineering jobs are added every week, free.',
        evidence: 'brief §5 thousands_weekly (prod ~2.7k/7d) + §10 P1',
      },
    ],
  },
  companies: {
    eyebrow: 'Companies',
    heading: 'Browse curated companies',
  },
  featureMatrix: {
    eyebrow: 'Features',
    heading: 'What you get.',
    features: [
      {
        id: 'freshness',
        name: 'Minutes, not weeks',
        detail: 'New roles land here minutes after posting.',
        evidence:
          'brief §5 minutes_after_posting (prod median 0.76h). Was "Seconds, not weeks" (owner-directed 2026-08-09); reworded 2026-09-10 when the proof strip put the 45-minute median in a headline two sections away, so the page states ONE freshness number. Reverting is a one-word edit if the owner prefers "seconds".',
      },
      {
        id: 'ai_labels',
        name: 'AI-labeled roles',
        detail: 'Level, category, and location on every job.',
        evidence: 'business-context §feature-set: AI-powered labeling, LIVE today',
      },
      {
        id: 'saved_filters',
        name: 'Saved filters',
        detail: 'Your searches, ready on every visit.',
        evidence: 'business-context §feature-set: saved filters, LIVE today',
      },
      {
        id: 'track_any_company',
        name: 'Track any company',
        detail: 'Name a company and we watch its board.',
        evidence:
          'EPIC Custom company sources wdwb1cbnc2; SHIPPED on main 2026-09-02, graduated out of the coming-soon tier 2026-09-03. Rollout is flag-gated (VITE_CUSTOM_COMPANIES_ENABLED + backend CUSTOM_COMPANY_SOURCES_ENABLED), so the claim is true where the flags are on.',
      },
      {
        id: 'reach_recruiter',
        name: 'Reach the recruiter',
        detail: 'One click to the people hiring, on LinkedIn.',
        evidence:
          'owner-directed 2026-08-09, backed by the job card’s LinkedIn people-search link. Moved out of the apply-early closer 2026-09-10 so that line could shrink.',
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
    ],
    nextUp: {
      label: 'Built with the community. Vote on what’s next.',
      to: ROUTES.VOTE_FEATURES,
    },
  },
  faq: {
    eyebrow: 'FAQ',
    heading: 'Frequently asked questions',
    entries: [
      {
        question: 'How fast do new jobs show up on onesecondswe?',
        answer:
          'A median of roughly 45 minutes after a company publishes the role on its own career page. onesecondswe continuously monitors 130+ company boards instead of waiting for jobs to be re-syndicated by aggregators.',
      },
      {
        question: 'How is onesecondswe different from LinkedIn?',
        answer:
          'onesecondswe reads company career pages directly and never reposts, so every posting date is the moment we first saw the job. LinkedIn lets companies repost a role with a fresh date and ranks promoted listings first. onesecondswe also covers a curated set of 130+ companies rather than anyone who posts.',
      },
      {
        question: 'Why do job postings on big boards look new but are actually old?',
        answer:
          'Aggregators re-syndicate listings and companies re-post roles, which resets the “posted” date without the job being new. onesecondswe never reposts: the date on every listing is when we first detected it on the employer’s own career page, so freshness is real, not recycled.',
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
  },
  closing: {
    heading: 'Be early, every time.',
    evidence: 'brief §4 supporting beat ("onesecondswe exists so you’re early, every time")',
  },
  footer: {
    links: [
      { label: 'Browse jobs', to: ROUTES.RECENT_JOBS },
      { label: 'Companies we track', to: ROUTES.CURATED_COMPANIES },
      { label: 'Why this was built', to: ROUTES.WHY },
      { label: 'Create free account', to: ROUTES.ACCOUNT },
    ],
  },
  seo: {
    title: 'Software Engineer Jobs, Minutes After They’re Posted | onesecondswe',
    description:
      'A free job board for software engineers. Jobs straight from 130+ curated company career pages, a median of 45 minutes after posting. No reposts, no noise.',
    siteUrl: 'https://onesecondswe.dev',
    canonicalPath: ROUTES.LANDING,
    ogImagePath: '/og-image.png',
  },
};
