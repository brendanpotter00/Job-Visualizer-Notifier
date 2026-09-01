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

function job(id: string, facets: { category?: string | null; level?: string | null } = {}): Job {
  return {
    id,
    source: 'backend-scraper',
    company: CUSTOM_ID,
    title: `Role ${id}`,
    location: 'Remote',
    createdAt: new Date().toISOString(),
    firstSeenAt: new Date().toISOString(),
    url: `https://example.com/${id}`,
    category: facets.category ?? null,
    level: facets.level ?? null,
    raw: {},
  };
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
