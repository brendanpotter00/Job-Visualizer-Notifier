import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChangelogColumn } from '../../../pages/VoteFeaturesPage/ChangelogColumn';

vi.mock('../../../config/changelog', async () => {
  const CHANGELOG_TAGS = ['feature', 'technical'] as const;
  type ChangelogTag = (typeof CHANGELOG_TAGS)[number];
  interface ChangelogEntry {
    id: string;
    title: string;
    description: string;
    tags: ChangelogTag[];
    date: string;
  }
  const CHANGELOG: readonly ChangelogEntry[] = [
    {
      id: 'old-technical',
      title: 'Old technical thing',
      description: 'Refactor of the old thing.',
      tags: ['technical'],
      date: '2026-01-10',
    },
    {
      id: 'feature-a',
      title: 'Feature A',
      description: 'Shipped feature A.',
      tags: ['feature'],
      date: '2026-04-18',
    },
    {
      id: 'feature-b',
      title: 'Feature B',
      description: 'Shipped feature B.',
      tags: ['feature'],
      date: '2026-04-18',
    },
  ];
  return { CHANGELOG, CHANGELOG_TAGS };
});

describe('ChangelogColumn', () => {
  it('with no tag selection renders every entry', () => {
    render(<ChangelogColumn />);
    expect(screen.getByText('Feature A')).toBeInTheDocument();
    expect(screen.getByText('Feature B')).toBeInTheDocument();
    expect(screen.getByText('Old technical thing')).toBeInTheDocument();
  });

  it('selecting "technical" narrows the list to technical-tagged entries only', async () => {
    const user = userEvent.setup();
    render(<ChangelogColumn />);

    await user.click(screen.getByRole('combobox', { name: /tags/i }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'technical' }));

    expect(screen.getByText('Old technical thing')).toBeInTheDocument();
    expect(screen.queryByText('Feature A')).not.toBeInTheDocument();
    expect(screen.queryByText('Feature B')).not.toBeInTheDocument();
  });

  it('renders entries newest-first when dates differ', () => {
    render(<ChangelogColumn />);
    const titles = screen
      .getAllByRole('heading', { level: 3 })
      .map((h) => h.textContent);
    const idxA = titles.indexOf('Feature A');
    const idxB = titles.indexOf('Feature B');
    const idxOld = titles.indexOf('Old technical thing');
    expect(idxA).toBeGreaterThanOrEqual(0);
    expect(idxB).toBeGreaterThanOrEqual(0);
    expect(idxOld).toBeGreaterThanOrEqual(0);
    expect(idxA).toBeLessThan(idxOld);
    expect(idxB).toBeLessThan(idxOld);
  });
});
