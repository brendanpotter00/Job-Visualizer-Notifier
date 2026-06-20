import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import type { CuratedCompany } from '../../../features/companies/companiesApi';

// Shrink the batch sizes so a small fixture exercises reveal-by-scroll cleanly.
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

// jsdom has no layout engine, so simulate one: page height = (rendered cards) ×
// CARD_H, a short viewport, and a controllable scroll position. With the grid's
// 300px reveal threshold, two cards (600px) under a 100px viewport are NOT near
// the bottom at scrollY 0, and each scroll-to-near-bottom reveals exactly one
// 2-card batch.
const CARD_H = 300;
const VIEWPORT_H = 100;

describe('CuratedCompaniesGrid infinite reveal', () => {
  let scrollY = 0;
  let originalInnerHeight = 0;

  beforeEach(() => {
    scrollY = 0;
    originalInnerHeight = window.innerHeight;
    window.innerHeight = VIEWPORT_H;
    Object.defineProperty(window, 'scrollY', { configurable: true, get: () => scrollY });
    Object.defineProperty(document.documentElement, 'scrollHeight', {
      configurable: true,
      get: () => document.querySelectorAll('h3').length * CARD_H,
    });
  });

  afterEach(() => {
    window.innerHeight = originalInnerHeight;
    delete (window as unknown as Record<string, unknown>).scrollY;
    delete (document.documentElement as unknown as Record<string, unknown>).scrollHeight;
    vi.clearAllMocks();
  });

  function scrollTo(y: number) {
    scrollY = y;
    act(() => {
      window.dispatchEvent(new Event('scroll'));
    });
  }

  it('reveals one batch per scroll-to-near-bottom and stops at the end', () => {
    renderWithProviders(<CuratedCompaniesGrid companies={COMPANIES} />);

    // Initial batch of 2 — at the top of 600px content, not near the bottom.
    expect(screen.getByRole('heading', { level: 3, name: 'Acme' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Bolt' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 3, name: 'Crux' })).not.toBeInTheDocument();
    expect(screen.queryByText(/all 5 companies shown/i)).not.toBeInTheDocument();

    // Scroll near the bottom of the 600px content → reveal one batch (2 → 4).
    scrollTo(300);
    expect(screen.getByRole('heading', { level: 3, name: 'Crux' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Delta' })).toBeInTheDocument();
    // Exactly one batch — Echo stays hidden and the end message is not shown yet.
    expect(screen.queryByRole('heading', { level: 3, name: 'Echo' })).not.toBeInTheDocument();
    expect(screen.queryByText(/all 5 companies shown/i)).not.toBeInTheDocument();

    // Scroll near the bottom of the 1200px content → reveal the final batch.
    scrollTo(900);
    expect(screen.getByRole('heading', { level: 3, name: 'Echo' })).toBeInTheDocument();
    expect(screen.getByText(/all 5 companies shown/i)).toBeInTheDocument();
  });
});
