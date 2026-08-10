import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { FreshJobsTriptych } from '../../../pages/AdminLandingPrototypesPage/sections/FreshJobsTriptych';
import { selectTriptychSlots } from '../../../pages/AdminLandingPrototypesPage/sections/triptychJobs';
import {
  buildMockJobs,
  buildSparseMockJobs,
} from '../../../pages/AdminLandingPrototypesPage/mockData';

const NOW = new Date('2026-08-09T18:00:00Z').getTime();
/** Mirrors FlippingCard's own constant so expectations track the real cadence. */
const INTERVAL_MS = 4500;
/** Mirrors FreshJobsTriptych's PHASE_STEP_MS. */
const PHASE_STEP_MS = 1500;

const RICH_JOBS = buildMockJobs(NOW);
const SPARSE_JOBS = buildSparseMockJobs(NOW);
const SLOTS = selectTriptychSlots(RICH_JOBS, NOW);
const [EARLY, DAY, BIG] = SLOTS;

const TEST_IDS = {
  early: 'triptych-slot-early_career',
  day: 'triptych-slot-last_24h',
  big: 'triptych-slot-big_tech',
} as const;

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

function renderTriptych(jobs = RICH_JOBS) {
  return renderWithProviders(<FreshJobsTriptych jobs={jobs} now={NOW} />, {
    initialEntries: ['/admin/landing-prototypes?proto=gravity'],
  });
}

function activeId(testId: string): string | null {
  return screen.getByTestId(testId).getAttribute('data-active-job-id');
}

/**
 * The one card a visitor actually sees in a slot. Read at rest (no timer
 * mid-advance), where exactly one exists — during the 300ms crossfade the
 * outgoing card briefly shares the cell.
 */
function activeCard(testId: string): HTMLElement {
  const cards = screen
    .getByTestId(testId)
    .querySelectorAll<HTMLElement>('[data-flip-role="active"]');
  expect(cards).toHaveLength(1);
  return cards[0];
}

/** The hidden height-reserving copies of the rest of the pool, in pool order. */
function sizers(testId: string): HTMLElement[] {
  return [
    ...screen.getByTestId(testId).querySelectorAll<HTMLElement>('[data-flip-role="sizer"]'),
  ];
}

/** Each sizer's job title, straight off the DOM (role queries can't see them). */
function sizerTitles(testId: string): (string | undefined)[] {
  return sizers(testId).map((s) => s.querySelector('h3')?.textContent ?? undefined);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('FreshJobsTriptych', () => {
  it('renders three labeled slots, each opening on its own freshest job', () => {
    renderTriptych();

    // The rich fixture is built to fill all three slots.
    expect(screen.getByText('Internships & new grad')).toBeInTheDocument();
    expect(screen.getByText('Posted in the last 24 hours')).toBeInTheDocument();
    expect(screen.getByText('Fresh from big tech')).toBeInTheDocument();
    expect([EARLY.label, DAY.label, BIG.label]).toEqual([
      'Internships & new grad',
      'Posted in the last 24 hours',
      'Fresh from big tech',
    ]);

    expect(activeId(TEST_IDS.early)).toBe(EARLY.jobs[0].id);
    expect(activeId(TEST_IDS.day)).toBe(DAY.jobs[0].id);
    expect(activeId(TEST_IDS.big)).toBe(BIG.jobs[0].id);
  });

  it('never shows the same job in two slots at once', () => {
    renderTriptych();
    const shown = [TEST_IDS.early, TEST_IDS.day, TEST_IDS.big].map(activeId);
    expect(new Set(shown).size).toBe(3);
  });

  it('renders three real JobListingCards (one Apply link per slot)', () => {
    renderTriptych();
    // Three links, not twelve: the hidden sizers behind each card are
    // aria-hidden, so role queries skip them entirely.
    expect(screen.getAllByRole('link', { name: /apply/i })).toHaveLength(3);
    expect(within(activeCard(TEST_IDS.early)).getByText(/^Posted /)).toBeInTheDocument();
  });

  // The layout-shift fix. One pool card — Microsoft's "Software Engineering
  // Intern, Azure Core (Summer 2027)", a three-line title over wrapping chips —
  // is taller than its slot-mates, and every time it rotated in the section
  // grew and shoved the rest of the page down a line. Each slot now renders a
  // hidden copy of EVERY job in its pool into the same grid cell as the visible
  // card, so the cell is the height of the tallest card from first paint and
  // stays there for the whole rotation. Immune by construction: it holds for
  // any pool, any title length, no measurement and no magic number.
  it('reserves the tallest card in each pool by rendering every job as a hidden sizer', () => {
    renderTriptych();

    for (const [slot, testId] of [
      [EARLY, TEST_IDS.early],
      [DAY, TEST_IDS.day],
      [BIG, TEST_IDS.big],
    ] as const) {
      expect(sizers(testId)).toHaveLength(slot.jobs.length);
      // Every job in the pool is present, in pool order — including the ones
      // not currently on screen. That is what makes the height a max(), not a
      // property of whichever card happens to be showing.
      expect(sizerTitles(testId)).toEqual(slot.jobs.map((j) => j.title));
    }
  });

  it('keeps the sizers out of the a11y tree, off the tab order and unpainted', () => {
    renderTriptych();

    for (const sizer of sizers(TEST_IDS.early)) {
      expect(sizer).toHaveAttribute('aria-hidden', 'true');
      expect(sizer).toHaveAttribute('inert');
      // visibility:hidden, NOT display:none — the box must keep its layout or
      // it would reserve nothing. It is what also drops the sizer out of
      // hit-testing and out of the tab order.
      expect(sizer).toHaveStyle({ visibility: 'hidden' });
    }

    // Not perceivable and not reachable: a job sitting in a sizer is in the DOM
    // but exposes no heading and no Apply link to a keyboard or screen-reader
    // user — still three Apply links on the page, one per visible card.
    const offscreenTitle = EARLY.jobs[1].title;
    expect(screen.queryByRole('heading', { name: offscreenTitle })).not.toBeInTheDocument();
    expect(screen.getAllByText(offscreenTitle).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /apply/i })).toHaveLength(3);
  });

  it('leaves the sizer stack untouched as the visible card flips', () => {
    vi.useFakeTimers();
    renderTriptych();
    const before = sizerTitles(TEST_IDS.early);

    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS);
    });

    // The active card advanced; the reserved height did not move with it.
    expect(activeId(TEST_IDS.early)).toBe(EARLY.jobs[1].id);
    expect(sizerTitles(TEST_IDS.early)).toEqual(before);
  });

  it('marks every swapping region aria-live="off" — the flips are decorative', () => {
    renderTriptych();
    for (const testId of Object.values(TEST_IDS)) {
      expect(screen.getByTestId(testId)).toHaveAttribute('aria-live', 'off');
    }
  });

  it('staggers the slots so they flip at different moments, not in unison', () => {
    vi.useFakeTimers();
    renderTriptych();
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    // Slot 0 (phase 0) goes first, alone.
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS);
    });
    expect(activeId(TEST_IDS.early)).toBe(EARLY.jobs[1].id);
    expect(activeId(TEST_IDS.day)).toBe(DAY.jobs[0].id);
    expect(activeId(TEST_IDS.big)).toBe(BIG.jobs[0].id);

    // Slot 1 (phase 1.5s) follows.
    act(() => {
      vi.advanceTimersByTime(PHASE_STEP_MS);
    });
    expect(activeId(TEST_IDS.day)).toBe(DAY.jobs[1].id);
    expect(activeId(TEST_IDS.big)).toBe(BIG.jobs[0].id);

    // Slot 2 (phase 3s) last.
    act(() => {
      vi.advanceTimersByTime(PHASE_STEP_MS);
    });
    expect(activeId(TEST_IDS.big)).toBe(BIG.jobs[1].id);
    // The lead slot has not lapped anyone in the meantime.
    expect(activeId(TEST_IDS.early)).toBe(EARLY.jobs[1].id);
  });

  it('keeps advancing each slot on its own phase after the first flip', () => {
    vi.useFakeTimers();
    renderTriptych();

    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * 2);
    });
    // t=9000: slot 0 has flipped twice (4500, 9000); slot 1 once (6000);
    // slot 2 once (7500).
    expect(activeId(TEST_IDS.early)).toBe(EARLY.jobs[2 % EARLY.jobs.length].id);
    expect(activeId(TEST_IDS.day)).toBe(DAY.jobs[1].id);
    expect(activeId(TEST_IDS.big)).toBe(BIG.jobs[1].id);
  });

  it('pausing one slot on hover leaves the other two rotating', () => {
    vi.useFakeTimers();
    renderTriptych();

    // React synthesizes onMouseEnter from the delegated mouseover event.
    fireEvent.mouseOver(screen.getByTestId(TEST_IDS.day));
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS + 2 * PHASE_STEP_MS);
    });

    expect(activeId(TEST_IDS.day)).toBe(DAY.jobs[0].id);
    expect(activeId(TEST_IDS.early)).toBe(EARLY.jobs[1].id);
    expect(activeId(TEST_IDS.big)).toBe(BIG.jobs[1].id);

    // Leaving restarts that slot's own phase without disturbing the others.
    fireEvent.mouseOut(screen.getByTestId(TEST_IDS.day));
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS + PHASE_STEP_MS);
    });
    expect(activeId(TEST_IDS.day)).toBe(DAY.jobs[1].id);
  });

  it('pauses a slot while focus is inside it', () => {
    vi.useFakeTimers();
    renderTriptych();

    act(() => {
      within(screen.getByTestId(TEST_IDS.early))
        .getByRole('link', { name: /apply/i })
        .focus();
    });
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * 3);
    });
    expect(activeId(TEST_IDS.early)).toBe(EARLY.jobs[0].id);
  });

  it('reduced motion: three static freshest cards and not a single timer', () => {
    defineMatchMedia(true);
    vi.useFakeTimers();
    renderTriptych();

    expect(vi.getTimerCount()).toBe(0);
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * 5);
    });
    expect(activeId(TEST_IDS.early)).toBe(EARLY.jobs[0].id);
    expect(activeId(TEST_IDS.day)).toBe(DAY.jobs[0].id);
    expect(activeId(TEST_IDS.big)).toBe(BIG.jobs[0].id);
    // No sizers either: a card that never changes has no height to reserve
    // against, so the reduced-motion path stays the leanest DOM of the three.
    for (const testId of Object.values(TEST_IDS)) {
      expect(sizers(testId)).toHaveLength(0);
    }
  });

  it('sparse fixture: an empty slot says so and points at the live board', () => {
    const sparseSlots = selectTriptychSlots(SPARSE_JOBS, NOW);
    expect(sparseSlots[0].jobs).toHaveLength(0);

    renderTriptych(SPARSE_JOBS);

    const emptySlot = screen.getByTestId(TEST_IDS.early);
    expect(emptySlot).toHaveAttribute('data-empty', 'true');
    expect(emptySlot).not.toHaveAttribute('data-active-job-id');
    expect(
      within(emptySlot).getByText('No internships or new-grad roles this week.')
    ).toBeInTheDocument();
    expect(within(emptySlot).getByRole('link', { name: 'Check the board' })).toHaveAttribute(
      'href',
      '/'
    );
    // The caption still names the slot honestly.
    expect(screen.getByText('Internships & new grad')).toBeInTheDocument();
    // ...and the slots that DO have jobs still render their cards.
    expect(activeId(TEST_IDS.big)).toBe(sparseSlots[2].jobs[0].id);
  });

  it('a single-job slot renders without scheduling a rotation timer', () => {
    vi.useFakeTimers();
    const sparseSlots = selectTriptychSlots(SPARSE_JOBS, NOW);
    expect(sparseSlots[1].jobs).toHaveLength(1);

    renderTriptych(SPARSE_JOBS);
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * 4);
    });
    expect(activeId(TEST_IDS.day)).toBe(sparseSlots[1].jobs[0].id);
    // ...and no sizer stack: with nothing to flip to, the visible card already
    // is the tallest card in its pool.
    expect(sizers(TEST_IDS.day)).toHaveLength(0);
  });

  it('renders nothing at all only when every pool is empty', () => {
    renderTriptych([]);
    expect(screen.queryByTestId('fresh-jobs-triptych')).not.toBeInTheDocument();
  });
});
