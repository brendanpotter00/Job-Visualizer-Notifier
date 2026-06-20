import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import type { CuratedCompany } from '../../../features/companies/companiesApi';

// Shrink the batch sizes so a small fixture forces two reveals (2 -> 4 -> 5),
// exercising both an intermediate batch and the final clamp — mirrors
// ChangelogColumn.multibatch.test.tsx.
vi.mock('../../../constants/ui', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    CHANGELOG_INFINITE_SCROLL_CONFIG: {
      INITIAL_BATCH_SIZE: 2,
      SUBSEQUENT_BATCH_SIZE: 2,
      SKELETON_COUNT: 1,
    },
  };
});

// Imported after the mock so the grid picks up the shrunken batch sizes.
import { CuratedCompaniesGrid } from '../../../pages/CuratedCompaniesPage/CuratedCompaniesGrid';

function c(id: string, displayName: string): CuratedCompany {
  return { id, displayName, ats: 'greenhouse', blurb: null, accomplishment: null };
}

// Names already alphabetical so reveal order is deterministic.
const COMPANIES = [
  c('a', 'Acme'),
  c('b', 'Bolt'),
  c('c', 'Crux'),
  c('d', 'Delta'),
  c('e', 'Echo'),
];

describe('CuratedCompaniesGrid infinite reveal', () => {
  let observerCallback: ((entries: { isIntersecting: boolean }[]) => void) | null = null;

  beforeEach(() => {
    observerCallback = null;
    class CapturingIntersectionObserver {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        observerCallback = cb;
      }
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    }
    global.IntersectionObserver =
      CapturingIntersectionObserver as unknown as typeof IntersectionObserver;
  });

  afterEach(() => vi.clearAllMocks());

  async function reveal() {
    await act(async () => {
      observerCallback?.([{ isIntersecting: true }]);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  it('reveals companies in batches as the sentinel scrolls into view', async () => {
    renderWithProviders(<CuratedCompaniesGrid companies={COMPANIES} />);

    // Initial batch of 2.
    expect(screen.getByRole('heading', { level: 3, name: 'Acme' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Bolt' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 3, name: 'Crux' })).not.toBeInTheDocument();
    expect(screen.queryByText(/all 5 companies shown/i)).not.toBeInTheDocument();

    // First reveal: 2 -> 4 (intermediate; end-of-list message stays hidden).
    await reveal();
    expect(screen.getByRole('heading', { level: 3, name: 'Crux' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Delta' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 3, name: 'Echo' })).not.toBeInTheDocument();
    expect(screen.queryByText(/all 5 companies shown/i)).not.toBeInTheDocument();

    // Second reveal: min(4 + 2, 5) = 5; everything shown + end-of-list message.
    await reveal();
    expect(screen.getByRole('heading', { level: 3, name: 'Echo' })).toBeInTheDocument();
    expect(screen.getByText(/all 5 companies shown/i)).toBeInTheDocument();
  });
});
