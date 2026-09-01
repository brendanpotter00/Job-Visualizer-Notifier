import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';

/**
 * The explanation for an empty chart on a freshly added board.
 *
 * A category or level filter requires a job to CARRY that facet, so an
 * unenriched job is hidden — correct, and unchanged. But enrichment lags a new
 * board badly (production: 1,246 of one board's 1,250 jobs had no enrichment row
 * at all), so a saved category filter empties the whole board and the page used
 * to say nothing about why.
 */
const { flagState } = vi.hoisted(() => ({ flagState: { isEnabled: true } }));
vi.mock('../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: {
    get isEnabled() {
      return flagState.isEnabled;
    },
    isDiscoveryProgressEnabled: false,
  },
}));

import { PendingEnrichmentNote } from '../../../components/companies-page/PendingEnrichmentNote';
import { createTestStore } from '../../../test/testUtils';
import { jobsApi } from '../../../features/jobs/jobsApi';
import type { Job } from '../../../types';

const CUSTOM_ID = 'u-jw8iz8sqvy';

function job(
  id: string,
  facets: { category?: string | null; level?: string | null; firstSeenAt?: string } = {}
): Job {
  const firstSeenAt = facets.firstSeenAt ?? new Date().toISOString();
  return {
    id,
    source: 'backend-scraper',
    company: CUSTOM_ID,
    title: `Role ${id}`,
    location: 'Remote',
    createdAt: firstSeenAt,
    firstSeenAt,
    url: `https://example.com/${id}`,
    category: facets.category ?? null,
    level: facets.level ?? null,
    raw: {},
  };
}

/** `days` ago, for the time-window case below. */
function daysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

interface Options {
  companyId?: string;
  category?: string[];
  level?: string[];
}

async function renderNote(jobs: Job[], options: Options = {}) {
  const companyId = options.companyId ?? CUSTOM_ID;
  const store = createTestStore({
    app: { selectedCompanyId: companyId, selectedATS: 'backend-scraper', isInitialized: true },
    graphFilters: {
      filters: {
        timeWindow: '90d',
        searchTags: undefined,
        location: undefined,
        employmentType: undefined,
        softwareOnly: false,
        category: options.category,
        level: options.level,
      },
      hydrated: true,
      userModified: false,
    },
  });
  await store.dispatch(
    jobsApi.util.upsertQueryData(
      'getJobsForCompany',
      { companyId },
      { jobs, metadata: { totalCount: jobs.length, fetchedAt: new Date().toISOString() } }
    )
  );
  render(
    <Provider store={store}>
      <PendingEnrichmentNote />
    </Provider>
  );
}

afterEach(() => {
  flagState.isEnabled = true;
});

describe('PendingEnrichmentNote', () => {
  it('says how many jobs the category filter is hiding, and why', async () => {
    await renderNote(
      [job('a', { category: 'software_engineering' }), job('b'), job('c'), job('d')],
      { category: ['software_engineering'] }
    );

    const note = screen.getByTestId('pending-enrichment-note');
    expect(note).toHaveTextContent('3 of 4 jobs are still being categorized');
    // Names the control that is actually set, not both of them.
    expect(note).toHaveTextContent('category filter is hiding them');
  });

  it('counts the level filter too, and names THAT one', async () => {
    await renderNote([job('a', { level: 'senior' }), job('b')], { level: ['senior'] });

    const note = screen.getByTestId('pending-enrichment-note');
    expect(note).toHaveTextContent('1 of 2');
    expect(note).toHaveTextContent('level filter is hiding it');
  });

  it('names both when both are set', async () => {
    await renderNote([job('a'), job('b')], {
      category: ['software_engineering'],
      level: ['senior'],
    });

    expect(screen.getByTestId('pending-enrichment-note')).toHaveTextContent(
      'category and level filters are hiding them'
    );
  });

  // The note promises "these appear once enrichment catches up". A job that
  // ALSO fails a facet it already carries would still be hidden afterwards, so
  // counting it would make that promise false.
  it('does not blame enrichment for a facet the job already carries and fails', async () => {
    await renderNote(
      [
        // Category pending, but the populated level loses to the level filter —
        // enrichment finishing would not reveal this one.
        job('a', { level: 'mid' }),
        // Category pending, level already matches — genuinely enrichment-only.
        job('b', { level: 'senior' }),
      ],
      { category: ['software_engineering'], level: ['senior'] }
    );

    const note = screen.getByTestId('pending-enrichment-note');
    expect(note).toHaveTextContent('1 of 2 jobs are still being categorized');
    // ...and it names ONLY the filter actually withholding that job. Both
    // filters are set, but every level here is already enriched.
    expect(note).toHaveTextContent('category filter is hiding it');
    expect(note).not.toHaveTextContent('category and level filters');
  });

  it('never counts a job a NON-enrichment filter already excluded', async () => {
    await renderNote(
      [
        // Unenriched, but outside the 90-day window the store is set to — the
        // time filter excludes it, and enrichment is not why it is missing.
        job('old', { firstSeenAt: daysAgo(200) }),
        job('new'),
      ],
      { category: ['software_engineering'] }
    );

    // 1 of 1: the out-of-window job is in neither the numerator nor the
    // denominator.
    expect(screen.getByTestId('pending-enrichment-note')).toHaveTextContent(
      '1 of 1 job is still being categorized'
    );
  });

  it('renders NOTHING when no enrichment filter is active — the common case', async () => {
    await renderNote([job('a'), job('b')]);

    expect(screen.queryByTestId('pending-enrichment-note')).not.toBeInTheDocument();
  });

  it('renders nothing when every job on the board is already enriched', async () => {
    await renderNote(
      [job('a', { category: 'software_engineering' }), job('b', { category: 'design' })],
      { category: ['software_engineering'] }
    );

    expect(screen.queryByTestId('pending-enrichment-note')).not.toBeInTheDocument();
  });

  it('says nothing for a curated company — they are long since enriched', async () => {
    await renderNote([job('a'), job('b')], {
      companyId: 'spacex',
      category: ['software_engineering'],
    });

    expect(screen.queryByTestId('pending-enrichment-note')).not.toBeInTheDocument();
  });

  it('says nothing with the custom-companies flag off', async () => {
    flagState.isEnabled = false;
    await renderNote([job('a'), job('b')], { category: ['software_engineering'] });

    expect(screen.queryByTestId('pending-enrichment-note')).not.toBeInTheDocument();
  });
});
