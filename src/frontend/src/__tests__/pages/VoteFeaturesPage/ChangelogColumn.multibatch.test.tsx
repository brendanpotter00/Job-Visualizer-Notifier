import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { ChangelogColumn } from '../../../pages/VoteFeaturesPage/ChangelogColumn';

// FIVE entries, all the same tag so no filtering is needed. With the overridden
// batch sizes below (INITIAL 2 / SUBSEQUENT 2) the reveal sequence is
// 2 → 4 → min(4 + 2, 5) = 5, i.e. TWO reveals. The first reveal is an
// INTERMEDIATE batch (hasMore still true, sentinel must re-arm); the second
// exercises the Math.min UPPER clamp (4 + 2 = 6 capped to the list length 5).
// Distinct descending dates make the sort order deterministic.
vi.mock('../../../config/changelog', () => {
  const CHANGELOG_TAGS = ['feature'] as const;
  const CHANGELOG = [
    {
      id: 'feat-1',
      title: 'Feature One',
      description: 'Shipped feature one.',
      tags: ['feature'],
      date: '2026-04-20',
    },
    {
      id: 'feat-2',
      title: 'Feature Two',
      description: 'Shipped feature two.',
      tags: ['feature'],
      date: '2026-04-19',
    },
    {
      id: 'feat-3',
      title: 'Feature Three',
      description: 'Shipped feature three.',
      tags: ['feature'],
      date: '2026-04-18',
    },
    {
      id: 'feat-4',
      title: 'Feature Four',
      description: 'Shipped feature four.',
      tags: ['feature'],
      date: '2026-04-17',
    },
    {
      id: 'feat-5',
      title: 'Feature Five',
      description: 'Shipped feature five.',
      tags: ['feature'],
      date: '2026-04-16',
    },
  ];
  return { CHANGELOG, CHANGELOG_TAGS };
});

// INITIAL 2 / SUBSEQUENT 2 over the 5-entry fixture forces two reveals so the
// intermediate-batch re-arm and the Math.min upper clamp both get exercised.
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

describe('ChangelogColumn multi-batch reveal', () => {
  let observerCallback: ((entries: { isIntersecting: boolean }[]) => void) | null = null;

  beforeEach(() => {
    observerCallback = null;
    // Capture the latest IntersectionObserver callback so tests can simulate
    // the sentinel scrolling into view. Must be a real constructor (a class):
    // the hook calls `new IntersectionObserver(...)`, which an arrow-function
    // mock can't satisfy.
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

  afterEach(() => {
    vi.clearAllMocks();
  });

  // Simulates the sentinel entering the viewport and lets the component's
  // deferred (setTimeout 0) batch bump run.
  async function revealNextBatch() {
    await act(async () => {
      observerCallback?.([{ isIntersecting: true }]);
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  it('reveals entries across two batches, capping the final bump at the list length', async () => {
    render(<ChangelogColumn />);

    // Initial mount: only the first batch of 2 is shown.
    expect(screen.getByText('Feature One')).toBeInTheDocument();
    expect(screen.getByText('Feature Two')).toBeInTheDocument();
    expect(screen.queryByText('Feature Three')).not.toBeInTheDocument();
    expect(screen.queryByText('Feature Four')).not.toBeInTheDocument();
    expect(screen.queryByText('Feature Five')).not.toBeInTheDocument();
    expect(screen.queryByText(/all 5 updates/i)).not.toBeInTheDocument();

    // First reveal: 2 → 4. This is the INTERMEDIATE batch — hasMore is still
    // true, so the 5th entry stays hidden, the end-of-list message must NOT
    // appear, and the sentinel must re-mount/re-arm for the next bump.
    await revealNextBatch();

    expect(screen.getByText('Feature One')).toBeInTheDocument();
    expect(screen.getByText('Feature Two')).toBeInTheDocument();
    expect(screen.getByText('Feature Three')).toBeInTheDocument();
    expect(screen.getByText('Feature Four')).toBeInTheDocument();
    expect(screen.queryByText('Feature Five')).not.toBeInTheDocument();
    // Still more to load — end-of-list message must stay hidden.
    expect(screen.queryByText(/all 5 updates/i)).not.toBeInTheDocument();

    // Second reveal: min(4 + 2, 5) = 5. The sentinel re-armed (proving the
    // intermediate state worked) and the Math.min clamp produced exactly 5,
    // not 6 — every entry is now shown and the end-of-list message appears.
    await revealNextBatch();

    expect(screen.getByText('Feature One')).toBeInTheDocument();
    expect(screen.getByText('Feature Two')).toBeInTheDocument();
    expect(screen.getByText('Feature Three')).toBeInTheDocument();
    expect(screen.getByText('Feature Four')).toBeInTheDocument();
    expect(screen.getByText('Feature Five')).toBeInTheDocument();
    expect(screen.getByText(/all 5 updates/i)).toBeInTheDocument();
  });
});
