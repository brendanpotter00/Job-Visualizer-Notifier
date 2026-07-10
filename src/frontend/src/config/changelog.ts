import { ROUTES } from './routes';

export const CHANGELOG_TAGS = ['feature', 'improvement', 'new-companies'] as const;
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
    id: 'add-brainco',
    title: 'Added Brain Co.',
    description:
      'Brain Co. — an applied-AI startup co-founded by Jared Kushner and Elad Gil that builds AI applications for institutions across government, healthcare, and other critical industries — is now tracked via its Ashby job board. The company recently emerged with backing from high-profile founders and is hiring across engineering, product, design, and operations in the San Francisco Bay Area.',
    tags: ['new-companies'],
    date: '2026-07-10',
    link: { to: ROUTES.ACCOUNT, label: 'Add Brain Co. to your company preferences' },
  },
  {
    id: 'mobile-friendly',
    title: 'The whole app now works on your phone',
    description:
      'Every page got a big mobile pass so the app is genuinely usable on a phone in portrait, not just the desktop layout shrunk down. On Recent Job Postings the full-screen metrics collapse into a compact row of numbers, the filters take far less room, and job cards are tighter so about five fit per screen. The company hiring graph renders in proper landscape proportions instead of squished, curated company cards plus the saved-filters and feedback pages compact down, and wide admin tables scroll sideways instead of overflowing the screen. It all runs on one shared set of responsive sizing tokens, so desktop and tablet (600px and up) stay pixel-for-pixel identical to before.',
    tags: ['improvement'],
    date: '2026-06-25',
    link: {
      to: ROUTES.RECENT_JOBS,
      label: 'Open the app on your phone',
    },
  },
  {
    id: 'add-salient',
    title: 'Added Salient',
    description:
      "Salient — an AI-native consumer-lending / loan-servicing platform (a16z- and Y Combinator-backed, $65M Series A) building the AI infrastructure behind financial operations — is now tracked via its Ashby job board. It ranked #2 on Harmonic's Hot 25 Startups list for Q3 2026, and is known for an exceptionally high talent density: a small, elite engineering team running the entire platform at scale.",
    tags: ['new-companies'],
    date: '2026-06-24',
    link: { to: ROUTES.ACCOUNT, label: 'Add Salient to your company preferences' },
  },
  {
    id: 'add-console',
    title: 'Added Console',
    description:
      'Console — an AI-native IT service management (ITSM) platform that automates 75%+ of service requests via natural language Playbooks and AI agents — is now tracked via its Ashby job board. The company is hiring across engineering, product, and GTM in San Francisco.',
    tags: ['new-companies'],
    date: '2026-06-22',
    link: { to: ROUTES.ACCOUNT, label: 'Add Console to your company preferences' },
  },
  {
    id: 'add-workos',
    title: 'Added WorkOS',
    description:
      'WorkOS — a developer-platform company whose APIs (SSO/SAML, Directory Sync/SCIM, AuthKit, and audit logs) let B2B apps ship the enterprise-readiness features large customers require — is now tracked via its Ashby job board. It is currently hiring across engineering and product, including AuthKit, infrastructure, and SRE roles, primarily remote across the US & Canada.',
    tags: ['new-companies'],
    date: '2026-06-22',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add WorkOS to your company preferences',
    },
  },
  {
    id: 'saved-filters',
    title: 'Save your default filters',
    description:
      'There’s a new Saved Filters page in the sidebar. Set the default time window for the Recent Jobs and Company Trends pages, pick a default set of locations once and have it apply to both, and build reusable keyword lists — named sets of include/exclude keywords that each save on their own with an Edit button when you want to change one. Choose a single active keyword list and it’s applied as your default filter across every page. Your defaults load automatically when you sign in and stay fully editable in the moment.',
    tags: ['feature'],
    date: '2026-06-21',
    link: {
      to: ROUTES.SAVED_FILTERS,
      label: 'Set your saved filters',
    },
  },
  {
    id: 'curated-companies',
    title: 'Browse the curated companies',
    description:
      'There’s a new Curated Companies page in the sidebar — a searchable grid of every company this site tracks, each with a short blurb on what it does and one thing it’s known for. It’s sorted alphabetically and pulls straight from the database, so a company added to the tracker shows up here automatically. Click any card to jump into that company’s hiring trends.',
    tags: ['feature'],
    date: '2026-06-19',
    link: {
      to: ROUTES.CURATED_COMPANIES,
      label: 'Browse curated companies',
    },
  },
  {
    id: 'add-reducto',
    title: 'Added Reducto',
    description:
      'Reducto — a document-ingestion / OCR API startup that turns complex PDFs and documents into LLM-ready structured data — is now tracked via its Ashby job board. It is currently hiring across engineering, product, and go-to-market roles in San Francisco.',
    tags: ['new-companies'],
    date: '2026-06-18',
    link: {
      to: ROUTES.SAVED_FILTERS,
      label: 'Add Reducto to your company preferences',
    },
  },
  {
    id: 'unified-company-filters',
    title: 'One set of filters on the Company page, plus a hideable graph',
    description:
      'On the Company Hiring Trends page the graph and the job list each had their own filters, with “Sync to List” / “Sync to Graph” buttons to copy one onto the other. Building this, I realized I always just ended up syncing the two together anyway — so I merged them into a single source of truth. The filters now drive the graph and the list at the same time: fewer clicks, nothing to keep in sync. I also added a “Hide graph” / “Show graph” toggle on the timeline header, for when you just want the job list without the chart.',
    tags: ['improvement'],
    date: '2026-06-14',
    link: {
      to: ROUTES.COMPANIES,
      label: 'See it on the Company Hiring Trends page',
    },
  },
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
    tags: ['feature'],
    date: '2026-06-14',
    link: {
      to: ROUTES.LOCATION_PIPELINE,
      label: 'See how it works',
    },
  },
  {
    id: 'add-workweave',
    title: 'Added Workweave',
    description:
      'Workweave — a Y Combinator (W25) startup whose product serves 200+ customers including Robinhood and PostHog — is now tracked via its Ashby job board. It is currently hiring across founding engineering, product, design, and go-to-market roles in San Francisco.',
    tags: ['new-companies'],
    date: '2026-06-12',
    link: {
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
      label: 'Turn auto-include on or off on the Saved Filters page',
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
      to: ROUTES.SAVED_FILTERS,
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
