import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { CategoryLevelDefaults } from '../../../components/saved-filters/CategoryLevelDefaults';

const baseProps = {
  category: [] as string[],
  level: [] as string[],
  onChangeCategory: () => {},
  onChangeLevel: () => {},
  dirty: false,
  saving: false,
  success: false,
  error: null,
  onSave: () => {},
};

/**
 * This section had no test file before the "Job title" -> "Job Category"
 * rename, so all four of its copy strings were unpinned. Two things are worth
 * pinning permanently:
 *
 * 1. The rename itself (heading, facet label, save button).
 * 2. The ABSENCE of "Jobs not yet enriched still appear." That sentence was
 *    false in all three places it appeared here: `useHydrateSavedFilters`
 *    pushes the saved category straight into a filter that HIDES unenriched
 *    rows, so the copy promised the opposite of the behaviour. Deleting it is
 *    the fix; this assertion is what stops it coming back.
 */
describe('CategoryLevelDefaults', () => {
  it('labels the category facet "Job Category", not "Job title"', () => {
    renderWithProviders(<CategoryLevelDefaults {...baseProps} />);

    expect(screen.getByRole('combobox', { name: 'Job Category' })).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Job title' })).not.toBeInTheDocument();
    expect(screen.getByText('Default job category & level')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save job category & level' })).toBeInTheDocument();
  });

  it('makes no claim that unenriched jobs still appear', () => {
    renderWithProviders(<CategoryLevelDefaults {...baseProps} />);

    // The positive half is what makes the negative half meaningful: assert the
    // corrected body copy is actually on screen, so this test cannot pass
    // simply because the paragraph failed to render at all.
    expect(screen.getByText(/Applied when you open either page/)).toBeInTheDocument();
    expect(screen.getByText(/Only jobs matching your selection are shown/)).toBeInTheDocument();
    expect(screen.queryByText(/not yet enriched still appear/i)).not.toBeInTheDocument();
  });
});
