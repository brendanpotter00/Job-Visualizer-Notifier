export const CHANGELOG_TAGS = ['feature', 'improvement', 'technical'] as const;
export type ChangelogTag = (typeof CHANGELOG_TAGS)[number];

export interface ChangelogEntry {
  id: string;
  title: string;
  description: string;
  tags: ChangelogTag[];
  date: string;
}

export const CHANGELOG: readonly ChangelogEntry[] = [
  {
    id: 'fetch-progress-chip-navigation',
    title: 'Jump to a company from the fetch progress bar',
    description:
      'Clicking a company chip in the Recent Jobs progress accordion now opens that company on the Company Job Postings page.',
    tags: ['improvement'],
    date: '2026-04-22',
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
