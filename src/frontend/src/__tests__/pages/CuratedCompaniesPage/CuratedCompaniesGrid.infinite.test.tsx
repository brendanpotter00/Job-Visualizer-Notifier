import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import type { CuratedCompany } from '../../../features/companies/companiesApi';

// Shrink the batch sizes so a small fixture exercises reveal-by-intersection.
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
    // Capture the latest IntersectionObserver callback so the test can simulate
    // the sentinel scrolling into view. The grid re-creates the observer after
    // each reveal, so this always points at the current callback.
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

  function sentinelIntersects() {
    act(() => observerCallback?.([{ isIntersecting: true }]));
  }

  it('reveals one batch each time the sentinel intersects, then stops at the end', () => {
    renderWithProviders(<CuratedCompaniesGrid companies={COMPANIES} />);

    // Initial batch of 2.
    expect(screen.getByRole('heading', { level: 3, name: 'Acme' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Bolt' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 3, name: 'Crux' })).not.toBeInTheDocument();
    expect(screen.queryByText(/all 5 companies shown/i)).not.toBeInTheDocument();

    // Sentinel scrolls into view → reveal exactly one batch (2 → 4).
    sentinelIntersects();
    expect(screen.getByRole('heading', { level: 3, name: 'Crux' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Delta' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 3, name: 'Echo' })).not.toBeInTheDocument();
    expect(screen.queryByText(/all 5 companies shown/i)).not.toBeInTheDocument();

    // Again → reveal the final batch and show the end message.
    sentinelIntersects();
    expect(screen.getByRole('heading', { level: 3, name: 'Echo' })).toBeInTheDocument();
    expect(screen.getByText(/all 5 companies shown/i)).toBeInTheDocument();
  });
});
