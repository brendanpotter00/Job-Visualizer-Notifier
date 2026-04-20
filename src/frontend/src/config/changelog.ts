export const CHANGELOG_TAGS = ['feature', 'technical'] as const;
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
    id: 'accounts',
    title: 'User accounts',
    description:
      'Sign in with Google or email to save your company preferences and personalize your view across devices.',
    tags: ['feature'],
    date: '2026-04-18',
  },
  {
    id: 'saved-company-preferences',
    title: 'Saved company preferences',
    description:
      'Choose the companies you care about on the Account page — your selection persists across sessions and drives the Recent Jobs view.',
    tags: ['feature'],
    date: '2026-04-18',
  },
];
