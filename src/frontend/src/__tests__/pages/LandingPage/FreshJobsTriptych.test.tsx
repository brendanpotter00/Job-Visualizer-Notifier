import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, fireEvent, screen, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { renderWithProviders } from '../../../test/testUtils';
import { FreshJobsTriptych } from '../../../pages/LandingPage/sections/FreshJobsTriptych';
import { selectTriptychSlots } from '../../../pages/LandingPage/sections/triptychJobs';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import type { Job } from '../../../types';
import {
  buildHolidayLandingJobs,
  buildRichLandingJobs,
  LANDING_NOW,
  makeLandingJob,
} from './landingJobFixtures';

const NOW = LANDING_NOW;
/** Mirrors FlippingCard's own constant so expectations track the real cadence. */
const INTERVAL_MS = 4500;
/** Mirrors FreshJobsTriptych's PHASE_STEP_MS. */
const PHASE_STEP_MS = 1500;

const RICH_JOBS = buildRichLandingJobs(NOW);
const QUIET_EARLY_JOBS = buildHolidayLandingJobs(NOW).filter(
  (job) => job.level !== 'intern' && job.level !== 'new_grad'
);
const SLOTS = selectTriptychSlots(RICH_JOBS, NOW);
const [EARLY, DAY, BIG] = SLOTS;
const CARD_LINK = LANDING_CONTENT.freshJobs.cardLink;

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

function renderTriptych(jobs: Job[] = RICH_JOBS) {
  const slots = selectTriptychSlots(jobs, NOW);
  return renderWithProviders(
    <Routes>
      <Route path="/" element={<FreshJobsTriptych slots={slots} cardLink={CARD_LINK} />} />
      <Route path="/jobs" element={<div>jobs board</div>} />
    </Routes>,
    { initialEntries: ['/'] }
  );
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
    expect(screen.getByText('Last 24 hours')).toBeInTheDocument();
    expect(screen.getByText('Big tech')).toBeInTheDocument();
    expect([EARLY.label, DAY.label, BIG.label]).toEqual([
      'Internships & new grad',
      'Last 24 hours',
      'Big tech',
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

  it('gives every visible card a link to the jobs board and an Apply link to its posting', () => {
    renderTriptych();

    expect(screen.getAllByRole('link', { name: CARD_LINK.label })).toHaveLength(3);
    for (const [testId, slot] of [
      [TEST_IDS.early, EARLY],
      [TEST_IDS.day, DAY],
      [TEST_IDS.big, BIG],
    ] as const) {
      const card = activeCard(testId);
      expect(within(card).getByRole('link', { name: CARD_LINK.label })).toHaveAttribute(
        'href',
        '/jobs'
      );
      const apply = within(card).getByRole('link', { name: /apply/i });
      expect(apply).toHaveAttribute('href', slot.jobs[0].url);
      expect(apply).toHaveAttribute('target', '_blank');
      expect(apply).toHaveAttribute('rel', 'noopener noreferrer');
    }
  });

  it('stacks the card link under Apply so Apply stays clickable', () => {
    renderTriptych();
    const card = activeCard(TEST_IDS.early);
    expect(within(card).getByRole('link', { name: CARD_LINK.label })).toHaveStyle({
      position: 'absolute',
      zIndex: '1',
    });
    expect(within(card).getByRole('link', { name: /apply/i })).toHaveStyle({
      position: 'relative',
      zIndex: '2',
    });
  });

  it('clicking the card body navigates to the jobs board without opening a tab', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    renderTriptych();

    fireEvent.click(within(activeCard(TEST_IDS.day)).getByRole('link', { name: CARD_LINK.label }));

    expect(screen.getByText('jobs board')).toBeInTheDocument();
    expect(screen.queryByTestId('fresh-jobs-triptych')).not.toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();
  });

  it('clicking Apply leaves the page alone and opens nothing from script', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    renderTriptych();

    const apply = within(activeCard(TEST_IDS.early)).getByRole('link', { name: /apply/i });
    apply.addEventListener('click', (event) => event.preventDefault());
    fireEvent.click(apply);

    expect(screen.getByTestId('fresh-jobs-triptych')).toBeInTheDocument();
    expect(screen.queryByText('jobs board')).not.toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();
  });

  it('clicking the title does not open the posting from script', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    renderTriptych();

    fireEvent.click(
      within(activeCard(TEST_IDS.big)).getByRole('heading', { name: BIG.jobs[0].title })
    );

    expect(open).not.toHaveBeenCalled();
  });

  it('pauses a slot while its card link has focus', () => {
    vi.useFakeTimers();
    renderTriptych();

    act(() => {
      within(activeCard(TEST_IDS.day)).getByRole('link', { name: CARD_LINK.label }).focus();
    });
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * 3);
    });
    expect(activeId(TEST_IDS.day)).toBe(DAY.jobs[0].id);
  });

  // The layout-shift fix. One pool card — Microsoft's "Software Engineering
  // Intern, Azure Core (Summer 2027)", a three-line title over wrapping chips —
  // is taller than its slot-mates, and every time it rotated in the section
  // grew and shoved the rest of the page down a line. Each slot now renders a
  // hidden copy of EVERY job in its pool into the same grid cell as the visible
  // card, so the cell is the height of the tallest card from first paint and
  // stays there for the whole rotation. Immune by construction: it holds for
  // any pool, any title length, no measurement and no magic number.
  it('reserves the tallest card in ANY slot by giving every slot a sizer for every job', () => {
    renderTriptych();

    const union = [...new Map(SLOTS.flatMap((slot) => slot.jobs).map((j) => [j.id, j])).values()];
    for (const testId of Object.values(TEST_IDS)) {
      expect(sizers(testId)).toHaveLength(union.length);
      expect(sizerTitles(testId)).toEqual(union.map((j) => j.title));
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
    for (const testId of Object.values(TEST_IDS)) {
      expect(sizers(testId).length).toBeGreaterThan(0);
    }
  });

  it('an empty slot says so and points at the live board', () => {
    const quietSlots = selectTriptychSlots(QUIET_EARLY_JOBS, NOW);
    expect(quietSlots[0].jobs).toHaveLength(0);

    renderTriptych(QUIET_EARLY_JOBS);

    const emptySlot = screen.getByTestId(TEST_IDS.early);
    expect(emptySlot).toHaveAttribute('data-empty', 'true');
    expect(emptySlot).not.toHaveAttribute('data-active-job-id');
    expect(
      within(emptySlot).getByText('None in the last 60 days.')
    ).toBeInTheDocument();
    expect(within(emptySlot).getByRole('link', { name: 'Browse jobs' })).toHaveAttribute(
      'href',
      '/jobs'
    );
    // The caption still names the slot honestly.
    expect(screen.getByText('Internships & new grad')).toBeInTheDocument();
    // ...and the slots that DO have jobs still render their cards.
    expect(activeId(TEST_IDS.big)).toBe(quietSlots[2].jobs[0].id);
  });

  it('a single-job slot renders without scheduling a rotation timer', () => {
    vi.useFakeTimers();
    const lone = [makeLandingJob(1, { company: 'ramp', hoursAgo: 3 }, NOW)];
    const loneSlots = selectTriptychSlots(lone, NOW);
    expect(loneSlots[1].jobs).toHaveLength(1);

    renderTriptych(lone);
    act(() => {
      vi.advanceTimersByTime(INTERVAL_MS * 4);
    });
    expect(activeId(TEST_IDS.day)).toBe(loneSlots[1].jobs[0].id);
    expect(sizers(TEST_IDS.day).length).toBeGreaterThan(0);
  });
});
