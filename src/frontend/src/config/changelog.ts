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
