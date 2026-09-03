/**
 * Curated "browse by category" taxonomy over the tracked-company roster.
 *
 * Pure data — no React, no side effects. `CompanyCategoriesSection` renders it;
 * the ids are validated against the real roster (`COMPANIES` in
 * `config/companies.ts`) by `__tests__/pages/LandingPage/companyCategories.test.ts`,
 * so a typo or a removed company fails the suite instead of shipping a blank tile.
 *
 * ── Conventions ────────────────────────────────────────────────────────────
 * • Categories are NOT mutually exclusive. Stripe is a YC alum, a unicorn, and
 *   fintech; that is the point — a visitor should find it from any of the three.
 * • `companyIds` is ordered MOST-RECOGNIZABLE-FIRST. The section renders only
 *   the first few logos on each card (the rest collapse into a "+N"), so the
 *   array order is load-bearing UI, not just data.
 * • Every category holds >= 5 companies. A category that could not reach five
 *   honestly was merged away rather than padded (see "Rejected" below).
 *
 * ── Taxonomy rationale ─────────────────────────────────────────────────────
 * Nine categories, sized to look substantial at a glance:
 *   big_tech            The FAANG tier + the public platforms beside it.
 *   ai_labs             STRICT: only companies training their own frontier
 *                       models (Anthropic/OpenAI/xAI/DeepMind tier). Deliberately
 *                       excludes the much larger set of "has an AI feature" and
 *                       "serves other people's models" companies — Together AI,
 *                       Fireworks, Baseten, fal, Perplexity and Cursor are
 *                       inference/product layers, not labs, and live in
 *                       dev_tools / breakout_startups instead. ElevenLabs and
 *                       Sesame train their own models but only in the audio
 *                       domain, so they are excluded from "frontier" too.
 *   yc_alumni           Y Combinator accelerator alumni. Lifetime status: going
 *                       public (Airbnb, Reddit, GitLab) does not remove it.
 *   unicorns            Private companies last valued at $1B+. Public companies,
 *                       wholly-acquired subsidiaries, and companies mid-exit are
 *                       excluded (see "Excluded as unverifiable").
 *   breakout_startups   Editorial, not a checkable claim: young companies whose
 *                       names already travel. No factual assertion is made.
 *   hard_tech           Space, defense, robotics and the tooling around them.
 *   fintech             Payments/banking + the proprietary trading firms. The
 *                       eight quant shops could not carry a standalone category
 *                       under the "each card must look substantial" bar, so they
 *                       merged in here and the label says "& trading".
 *   dev_tools           What engineers use to ship and run software, including
 *                       the model-serving layer.
 *   household_names     Brands recognized off the job market. Deliberately omits
 *                       Google/Apple/Microsoft/Nvidia/Adobe — they already carry
 *                       big_tech, and splitting them keeps the two cards visually
 *                       distinct instead of showing the same six logos twice.
 *
 * ── Verification (2026-08-09) ──────────────────────────────────────────────
 * "YC alumnus" and "unicorn" are checkable claims about real companies, so every
 * uncertain assignment went through Sonnet research subagents with web search
 * (four batches, ~100 companies), each returning YC batch + current valuation +
 * a source. Confirmed YC batches: Reddit S05, Dropbox S07, Twitch W07, Airbnb
 * W09, Stripe S09, Instacart S12, DoorDash S13, GitLab W15, Astranis W16, Scale
 * AI S16, Brex W17, Retool W17, Gem S17, Hightouch S19, EliseAI W19 (as
 * MeetElise), Ramp W19, Supabase S20, PostHog W20, Mintlify W22, Exa W22 (as
 * Metaphor), fal W22, Pylon W23, Salient W23, HappyRobot S23, GigaML S23,
 * Reducto W24, Workweave W25 (listed on YC as "Weave"). Confirmed NOT YC despite
 * folklore: Plaid, Notion, Linear, Vercel, Sentry, WorkOS, Merge, Airtable,
 * Braintrust, Applied Intuition (its founder was YC's COO; the company was not a
 * batch company), Traversal and Resolve AI (both name-collide with unrelated YC
 * companies).
 *
 * ── Excluded as unverifiable / mid-exit ────────────────────────────────────
 * Left OUT of `unicorns` on purpose rather than guessed:
 *   brex           acquired by Capital One (closed Apr 2026) — no longer independent.
 *   airtable       signed acquisition by Bending Spoons announced 2026-08-04, unclosed.
 *   cursor         reported pending acquisition; status too unsettled to assert.
 *   spacex, xai    reported 2026 IPO / merger activity that the subagent itself
 *                  flagged as needing corroboration. Both stay in the categories
 *                  that do not depend on private-valuation status (hard_tech,
 *                  ai_labs).
 *   poke           acquired by Cognition (Jul 2026), below $1B.
 *   turo           historically >$1B but no current figure; IPO filed, never priced.
 *   blueorigin     privately held by its founder, no externally priced valuation.
 *   sesame, wispr-flow, traversal, reducto, pylon-labs
 *                  valuations undisclosed or unconfirmed — no claim made.
 * Also excluded from `unicorns`: Waymo, Zoox, Twitch, Slack, Crunchyroll
 * (subsidiaries) and Squarespace (PE-owned).
 *
 * ── Rejected categories ────────────────────────────────────────────────────
 *   health & bio      the roster has no honest cluster (Neuralink alone).
 *   quant trading     8 firms, folded into fintech (see above).
 *   gaming/media      7 firms, folded into household_names.
 */

/** One curated entry point: a label, a one-line pitch, and its member roster. */
export interface CompanyCategory {
  /** Stable slug. Becomes the preset-filter key when categories are promoted. */
  id: string;
  /** Card heading. */
  label: string;
  /** One concrete line under the heading. */
  blurb: string;
  /** Member company ids, most-recognizable-first (see file header). */
  companyIds: readonly string[];
}

export const COMPANY_CATEGORIES: readonly CompanyCategory[] = [
  {
    id: 'big_tech',
    label: 'Big tech',
    blurb: 'The FAANG tier and the public platforms beside it.',
    companyIds: [
      'google',
      'apple',
      'microsoft',
      'netflix',
      'nvidia',
      'adobe',
      'airbnb',
      'spotify',
      'snap',
      'reddit',
      'pinterest',
      'dropbox',
      'block',
      'twitch',
      'slack',
      'figma',
    ],
  },
  {
    id: 'ai_labs',
    label: 'AI labs',
    blurb: 'The teams training their own frontier models.',
    companyIds: ['openai', 'anthropic', 'google', 'xai', 'cohere', 'thinkingmachines'],
  },
  {
    id: 'yc_alumni',
    label: 'Y Combinator alumni',
    blurb: 'Companies that came out of a YC batch, from S05 to W25.',
    companyIds: [
      'airbnb',
      'stripe',
      'reddit',
      'dropbox',
      'doordashusa',
      'instacart',
      'twitch',
      'gitlab',
      'brex',
      'scaleai',
      'ramp',
      'supabase',
      'retool',
      'posthog',
      'hightouch',
      'astranis',
      'exa',
      'fal',
      'mintlify',
      'gem',
      'eliseai',
      'salient',
      'pylon-labs',
      'happyrobot.ai',
      'gigaml',
      'reducto',
      'workweave',
    ],
  },
  {
    id: 'unicorns',
    label: 'Unicorns',
    blurb: 'Still private, last valued at a billion dollars or more.',
    companyIds: [
      'openai',
      'anthropic',
      'stripe',
      'databricks',
      'andurilindustries',
      'notion',
      'ramp',
      'discord',
      'figureai',
      'perplexity',
      'plaid',
      'scaleai',
      'elevenlabs',
      'cognition',
      'sierra',
      'harvey',
      'thinkingmachines',
      'cohere',
      'vercel',
      'supabase',
      'linear',
      'neuralink',
      'gleanwork',
      'appliedintuition',
      'saronic',
      'astranis',
      'nuro',
      'decagon',
      'granola',
      'exa',
      'fal',
      'baseten',
      'modal',
      'langchain',
      'togetherai',
      'fireworksai',
      'distyl',
      'resolve-ai',
      'apex-technology-inc',
      'base-power',
      'nominal',
      'posthog',
      'sentry',
      'retool',
      'hightouch',
      'gem',
      'clickup',
      'eliseai',
    ],
  },
  {
    id: 'breakout_startups',
    label: 'Breakout startups',
    blurb: 'Small teams whose names already travel further than their headcount.',
    companyIds: [
      'cursor',
      'perplexity',
      'elevenlabs',
      'cognition',
      'sierra',
      'harvey',
      'linear',
      'supabase',
      'thinkingmachines',
      'decagon',
      'granola',
      'exa',
      'fal',
      'baseten',
      'modal',
      'langchain',
      'browserbase',
      'wispr-flow',
      'krea',
    ],
  },
  {
    id: 'hard_tech',
    label: 'Space, defense & robotics',
    blurb: 'Rockets, satellites, drones, robots, and the software that runs them.',
    companyIds: [
      'spacex',
      'palantir',
      'andurilindustries',
      'blueorigin',
      'waymo',
      'neuralink',
      'zoox',
      'figureai',
      'nuro',
      'astranis',
      'saronic',
      'appliedintuition',
      'apex-technology-inc',
      'nominal',
      'siftstack',
      'flowengineering',
    ],
  },
  {
    id: 'fintech',
    label: 'Fintech & trading',
    blurb: 'Payments, banking, and the firms that trade the markets.',
    companyIds: [
      'stripe',
      'paypal',
      'block',
      'capitalone',
      'robinhood',
      'affirm',
      'plaid',
      'ramp',
      'brex',
      'jumptrading',
      'hrt',
      'optiver',
      'drw',
      'imc',
      'ctc',
      'akunacapital',
      'belvederetrading',
      'salient',
      'sunday',
    ],
  },
  {
    id: 'dev_tools',
    label: 'Developer tools & infrastructure',
    blurb: 'What engineers use to build, ship, and run everything else.',
    companyIds: [
      'cloudflare',
      'gitlab',
      'mongodb',
      'datadog',
      'snowflake',
      'databricks',
      'twilio',
      'vercel',
      'sentry',
      'supabase',
      'linear',
      'cursor',
      'posthog',
      'retool',
      'workos',
      'mintlify',
      'chalk',
      'braintrust',
      'hightouch',
      'merge',
      'modal',
      'baseten',
      'browserbase',
      'langchain',
      'fal',
      'fireworksai',
      'togetherai',
      'resolve-ai',
      'traversal',
      'judgmentlabs',
    ],
  },
  {
    id: 'household_names',
    label: 'Household names',
    blurb: 'Brands you knew long before you knew they were hiring.',
    companyIds: [
      'netflix',
      'disney',
      'spotify',
      'airbnb',
      'reddit',
      'discord',
      'roblox',
      'snap',
      'pinterest',
      'twitch',
      'dropbox',
      'slack',
      'lyft',
      'doordashusa',
      'instacart',
      'paypal',
      'capitalone',
      'expedia',
      'crunchyroll',
      'turo',
      'squarespace',
      'robinhood',
      'gm',
      'clear',
    ],
  },
];
