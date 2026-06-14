import { ROUTES } from './routes';

export const CHANGELOG_TAGS = [
  'feature',
  'improvement',
  'technical',
  'new-companies',
] as const;
export type ChangelogTag = (typeof CHANGELOG_TAGS)[number];

export interface ChangelogLink {
  to: string;
  label: string;
}

export interface ChangelogEntry {
  id: string;
  title: string;
  description: string;
  tags: ChangelogTag[];
  date: string;
  link?: ChangelogLink;
}

export const CHANGELOG: readonly ChangelogEntry[] = [
  {
    id: 'give-feedback',
    title: 'Give Feedback',
    description:
      'The “Vote for features” page is now “Give Feedback” — there’s a new feedback box at the top where you can send a note, suggestion, bug report, or request directly to me (signed in or not). The feature voting and changelog you already know stay right underneath.',
    tags: ['improvement'],
    date: '2026-06-14',
    link: {
      to: ROUTES.VOTE_FEATURES,
      label: 'Leave feedback',
    },
  },
  {
    id: 'location-normalization',
    title: 'Location normalization',
    description:
      'Job locations from every source are now standardized into consistent, structured city, region, country, and remote fields. A deterministic alias cache resolves about 90% of raw location strings instantly, and Claude Haiku 4.5 normalizes the rest, including multi-location postings and region-scoped remotes, caching every result for reuse. Normalization runs off the request path on a background worker, with a periodic safety-net task for stragglers and a golden-set eval harness guarding output quality.',
    tags: ['feature', 'technical'],
    date: '2026-06-13',
  },
  {
    id: 'add-workweave',
    title: 'Added Workweave',
    description:
      'Workweave — a Y Combinator (W25) startup whose product serves 200+ customers including Robinhood and PostHog — is now tracked via its Ashby job board. It is currently hiring across founding engineering, product, design, and go-to-market roles in San Francisco.',
    tags: ['new-companies'],
    date: '2026-06-12',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add Workweave to your company preferences',
    },
  },
  {
    id: 'add-quant-firms',
    title: 'Added 8 quant trading firms',
    description:
      'Eight of the largest quantitative / proprietary trading firms are now tracked: Jump Trading, DRW, Akuna Capital, Optiver, IMC Trading, Chicago Trading (CTC), and Hudson River Trading via their Greenhouse boards, plus Belvedere Trading via Lever.',
    tags: ['new-companies'],
    date: '2026-06-11',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add them to your company preferences',
    },
  },
  {
    id: 'auto-enroll-new-companies',
    title: 'New companies join your list automatically',
    description:
      'If you’ve curated a set of companies on the Account page, companies we add afterward now show up in your feed automatically — no need to come back and re-add each one. A new “Auto-include newly added companies” toggle on the Account page is on by default; turn it off to keep your list frozen to exactly what you picked.',
    tags: ['feature'],
    date: '2026-06-07',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Turn auto-include on or off on your Account page',
    },
  },
  {
    id: 'add-poke',
    title: 'Added Poke',
    description:
      'Poke — the proactive AI assistant from The Interaction Company of California that lives inside iMessage, WhatsApp, SMS, and Telegram to handle daily planning, scheduling, and follow-ups entirely by text — is now tracked via its Ashby job board. Founded by the ex-TUM Boring team (winners of SpaceX’s Not-a-Boring tunneling competition), it became the first AI agent approved on Apple’s Messages for Business platform in 2026 and has raised ~$25M from General Catalyst and Spark Capital at a ~$300M valuation.',
    tags: ['new-companies'],
    date: '2026-06-06',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add Poke to your company preferences',
    },
  },
  {
    id: 'add-posthog',
    title: 'Added PostHog',
    description:
      'PostHog — the open-source product analytics platform (YC W20) that bundles analytics, session replay, feature flags, A/B testing, surveys, and error tracking into a single tool for product engineers, serving 190k+ customers including ~65% of Y Combinator companies — is now tracked via its Ashby job board. PostHog reached unicorn status in 2025 with a $75M Series E led by Peak XV at a $1.4B valuation.',
    tags: ['new-companies'],
    date: '2026-06-04',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add PostHog to your company preferences',
    },
  },
  {
    id: 'add-fal',
    title: 'Added fal',
    description:
      'fal — the generative media cloud serving 1,000+ image, video, audio, and 3D models through one API to 2.5M+ developers and companies like Canva, Adobe, and Amazon MGM Studios — is now tracked via its Greenhouse job board. fal raised a $140M round led by Sequoia at a $4.5B valuation.',
    tags: ['new-companies'],
    date: '2026-05-30',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add fal to your company preferences',
    },
  },
  {
    id: 'add-vizcom',
    title: 'Added Vizcom',
    description:
      'Vizcom — the AI industrial design platform that turns sketches into photorealistic renders and 3D models for automotive, footwear, and consumer goods teams at Ford and New Balance, serving 700k+ designers — is now tracked via its Ashby job board. Vizcom has raised a $27M Series B led by Radical Ventures.',
    tags: ['new-companies'],
    date: '2026-05-30',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add Vizcom to your company preferences',
    },
  },
  {
    id: 'add-krea',
    title: 'Added Krea',
    description:
      'Krea — the San Francisco GenAI creative platform unifying 64+ image and video models (Veo, Sora, Kling, Runway) plus real-time generation and custom model training, used by creators at Pixar, LEGO, and Samsung — is now tracked via its Ashby job board. Krea raised an $83M round at a $500M valuation.',
    tags: ['new-companies'],
    date: '2026-05-30',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add Krea to your company preferences',
    },
  },
  {
    id: 'add-trajectory',
    title: 'Added Trajectory',
    description:
      'Trajectory — the Palo Alto AI startup from ex-Google DeepMind and Apple researchers building multimodal models with stronger visual reasoning for robotics, autonomous vehicles, and manufacturing — is now tracked via its Ashby job board.',
    tags: ['new-companies'],
    date: '2026-05-29',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add Trajectory to your company preferences',
    },
  },
  {
    id: 'add-sierra',
    title: 'Added Sierra',
    description:
      'Sierra — the customer-experience AI company co-founded by former Salesforce co-CEO Bret Taylor and ex-Google VP Clay Bavor that builds autonomous AI agents for enterprise customer service (used by SoFi, Ramp, and Brex) — is now tracked via its Ashby job board. Sierra recently raised ~$950M at a ~$15.8B valuation.',
    tags: ['new-companies'],
    date: '2026-05-27',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add Sierra to your company preferences',
    },
  },
  {
    id: 'add-roblox',
    title: 'Added Roblox',
    description:
      'Roblox — the user-generated immersive gaming platform with 132M daily active users — is now tracked via its Greenhouse job board.',
    tags: ['new-companies'],
    date: '2026-05-21',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add Roblox to your company preferences',
    },
  },
  {
    id: 'add-exa',
    title: 'Added Exa',
    description:
      'Exa — the AI-native search engine that powers Cursor, Cognition, HubSpot, and 400k+ developers — is now tracked via its Ashby job board. Exa just closed a $250M Series C at a $2.2B valuation.',
    tags: ['new-companies'],
    date: '2026-05-21',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add Exa to your company preferences',
    },
  },
  {
    id: 'add-paypal',
    title: 'Added PayPal',
    description:
      'PayPal is now tracked via its Workday job board, joining the other Workday-hosted companies in Recent Jobs and Company Hiring Trends.',
    tags: ['new-companies'],
    date: '2026-05-15',
  },
  {
    id: 'brand-refresh',
    title: 'New brand mark in the app bar',
    description:
      'The header now shows the onesecondswe wordmark with the 1s logo and a blinking green dot, all set in Infra Mono. Favicon and social preview image were refreshed to match.',
    tags: ['improvement'],
    date: '2026-04-22',
  },
  {
    id: 'cross-page-jobs-cache',
    title: 'Faster navigation between Recent Jobs and Company pages',
    description:
      'Jobs loaded on the Recent Jobs page are now shared with the Company Hiring Trends pages, so clicking into a company renders instantly from cache instead of re-fetching.',
    tags: ['improvement'],
    date: '2026-04-22',
  },
  {
    id: 'fetch-progress-chip-navigation',
    title: 'Jump to a company from the fetch progress bar',
    description:
      'Clicking a company chip in the Recent Jobs progress accordion now opens that company on the Company Job Postings page.',
    tags: ['improvement'],
    date: '2026-04-22',
  },
  {
    id: 'top-talent-density-companies',
    title: 'Added top talent-density startups',
    description:
      'Added Thinking Machines, Cursor, Modal Labs, LangChain, Together AI, Cognition, and Paraform — top-ranked startups on the Paraform Talent Density Index for concentrated senior engineering talent.',
    tags: ['new-companies'],
    date: '2026-04-22',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add these to your company preferences',
    },
  },
  {
    id: 'vote-for-features',
    title: 'Vote for features',
    description:
      'New page with a changelog of recent work and a voting column where signed-in users can upvote candidate features to help prioritize what ships next.',
    tags: ['feature'],
    date: '2026-04-21',
  },
  {
    id: 'saved-company-preferences',
    title: 'Saved company preferences',
    description:
      'Choose the companies you care about on the Account page — your selection persists across sessions and drives the Recent Jobs view.',
    tags: ['feature'],
    date: '2026-04-19',
  },
  {
    id: 'accounts',
    title: 'User accounts',
    description:
      'Sign in with Google or email to personalize your view across devices. A stepping stone toward saving preferences like location, companies, and notifications.',
    tags: ['feature'],
    date: '2026-04-18',
  },
];
