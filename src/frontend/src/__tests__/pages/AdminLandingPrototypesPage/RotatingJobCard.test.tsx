import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { RotatingJobCard } from '../../../pages/AdminLandingPrototypesPage/sections/RotatingJobCard';
import { selectTickerJobs } from '../../../pages/AdminLandingPrototypesPage/sections/tickerJobs';
import { TOP_COMPANY_IDS } from '../../../pages/AdminLandingPrototypesPage/content';
import {
  buildMockJobs,
  buildSparseMockJobs,
} from '../../../pages/AdminLandingPrototypesPage/mockData';

const NOW = new Date('2026-08-09T18:00:00Z').getTime();
/** Mirrors the component's own default so expectations track the real pool. */
const MAX_ITEMS = 6;
const INTERVAL_MS = 4500;

const RICH_JOBS = buildMockJobs(NOW);
const { items: EXPECTED } = selectTickerJobs(RICH_JOBS, TOP_COMPANY_IDS, NOW, MAX_ITEMS);

// jsdom does not implement matchMedia at all; usePrefersReducedMotion guards
// that absence (→ motion allowed). Only the reduced-motion case defines it.
function defineMatchMedia(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))
  );
}

function renderCard(jobs = RICH_JOBS) {
  return renderWithProviders(<RotatingJobCard jobs={jobs} now={NOW} />, {
    initialEntries: ['/admin/landing-prototypes?proto=gravity'],
  });
}

function region() {
  return screen.getByTestId('rotating-job-card');
}

/**
 * The one card a visitor actually sees. Read at rest (no timer mid-advance),
 * where exactly one exists — during the 300ms crossfade the outgoing card
 * briefly shares the cell.
 */
function activeCard(): HTMLElement {
  const cards = region().querySelectorAll<HTMLElement>('[data-flip-role="active"]');
  expect(cards).toHaveLength(1);
  return cards[0];
}

/** The hidden height-reserving copies of the rest of the pool, in pool order. */
function sizers(): HTMLElement[] {
  return [...region().querySelectorAll<HTMLElement>('[data-flip-role="sizer"]')];
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('RotatingJobCard', () => {
  it('opens on the freshest job under the honest 48h caption', () => {
    renderCard();
    expect(screen.getByText('Posted in the last 48 hours')).toBeInTheDocument();
    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[0].id);
    // By ROLE, not by text: the rest of the pool is in the DOM as hidden height
    // sizers (see FlippingCard's SizerStack), and those are aria-hidden, so a
    // role query sees only the job actually on screen.
    expect(within(region()).getByRole('heading', { name: EXPECTED[0].title })).toBeInTheDocument();
    // One card PERCEIVABLE at a time — not the old rail of little pills.
    expect(
      within(region()).queryByRole('heading', { name: EXPECTED[1].title })
    ).not.toBeInTheDocument();
  });

  it('renders a real JobListingCard (Apply link + posted-ago), not a mini row', () => {
    renderCard();
    // One link, not six: the sizers holding the rest of the pool are
    // aria-hidden, so role queries skip them entirely.
    const applyLinks = screen.getAllByRole('link', { name: /apply/i });
    expect(applyLinks).toHaveLength(1);
    expect(applyLinks[0]).toHaveAttribute('href', EXPECTED[0].url);
    expect(within(activeCard()).getByText(/^Posted /)).toBeInTheDocument();
  });

  // Signal's single card rides the exact same mechanic as the triptych slots,
  // so the triptych's layout-shift fix lands here for free — a tall job in the
  // pool can no longer grow the section when it rotates in. Asserted here so a
  // future fork of the behavior fails loudly instead of silently.
  it('reserves the tallest card in the pool by rendering every job as a hidden sizer', () => {
    renderCard();

    expect(sizers()).toHaveLength(EXPECTED.length);
    expect(sizers().map((s) => s.querySelector('h3')?.textContent)).toEqual(
      EXPECTED.map((j) => j.title)
    );
    for (const sizer of sizers()) {
      expect(sizer).toHaveAttribute('aria-hidden', 'true');
      expect(sizer).toHaveAttribute('inert');
      // visibility:hidden, NOT display:none — the box must keep its layout or
      // it would reserve nothing.
      expect(sizer).toHaveStyle({ visibility: 'hidden' });
    }
  });

  it('leaves the sizer stack untouched as the visible card flips', () => {
    vi.useFakeTimers();
    renderCard();
    const before = sizers().map((s) => s.querySelector('h3')?.textContent);

    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS);
    });

    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[1].id);
    expect(sizers().map((s) => s.querySelector('h3')?.textContent)).toEqual(before);
  });

  it('auto-advances to the next fresh job on the rotation interval', () => {
    vi.useFakeTimers();
    renderCard();
    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[0].id);

    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS);
    });
    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[1].id);
    expect(within(region()).getByRole('heading', { name: EXPECTED[1].title })).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS);
    });
    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[2].id);
  });

  it('wraps back to the freshest job after the last one', () => {
    vi.useFakeTimers();
    renderCard();
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * EXPECTED.length);
    });
    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[0].id);
  });

  // React synthesizes onMouseEnter/onMouseLeave from the delegated
  // mouseover/mouseout pair, so those are the events to dispatch here.
  it('pauses rotation while the card is hovered and resumes on leave', () => {
    vi.useFakeTimers();
    renderCard();

    fireEvent.mouseOver(region());
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * 3);
    });
    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[0].id);

    fireEvent.mouseOut(region());
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS);
    });
    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[1].id);
  });

  it('pauses rotation while focus is inside the card', () => {
    vi.useFakeTimers();
    renderCard();

    act(() => {
      screen.getByRole('link', { name: /apply/i }).focus();
    });
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * 3);
    });
    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[0].id);
  });

  it('marks the swapping region aria-live="off" — the flip is decorative', () => {
    renderCard();
    expect(region()).toHaveAttribute('aria-live', 'off');
  });

  it('reduced motion: one static freshest card, no interval, no rotation', () => {
    defineMatchMedia(true);
    vi.useFakeTimers();
    renderCard();

    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[0].id);
    expect(screen.getAllByRole('link', { name: /apply/i })).toHaveLength(1);
    // Nothing scheduled: no rotation timer exists to advance.
    expect(vi.getTimerCount()).toBe(0);
    // No sizers either: a card that never changes has no height to reserve
    // against, so the reduced-motion path stays the leanest DOM of the two.
    expect(sizers()).toHaveLength(0);

    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * 4);
    });
    expect(region()).toHaveAttribute('data-active-job-id', EXPECTED[0].id);
    expect(screen.getByText(EXPECTED[0].title)).toBeInTheDocument();
  });

  it('sparse fixture: caption widens to the honest week window', () => {
    const sparse = buildSparseMockJobs(NOW);
    const { items, mode } = selectTickerJobs(sparse, TOP_COMPANY_IDS, NOW, MAX_ITEMS);
    expect(mode).toBe('week');

    renderCard(sparse);
    expect(screen.getByText('Fresh this week')).toBeInTheDocument();
    expect(screen.queryByText('Posted in the last 48 hours')).not.toBeInTheDocument();
    expect(region()).toHaveAttribute('data-active-job-id', items[0].id);
  });

  it('renders nothing when there are no jobs to show', () => {
    renderCard([]);
    expect(screen.queryByTestId('rotating-job-card')).not.toBeInTheDocument();
  });
});
