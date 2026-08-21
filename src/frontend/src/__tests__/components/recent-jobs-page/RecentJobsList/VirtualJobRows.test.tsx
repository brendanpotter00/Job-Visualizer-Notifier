import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import { VirtualJobRows } from '../../../../components/recent-jobs-page/RecentJobsList/VirtualJobRows';
import { VIRTUAL_LIST_CONFIG } from '../../../../constants/ui';
import type { Job } from '../../../../types';

/**
 * jsdom performs no layout, so every element reports `offsetHeight: 0` and the
 * virtualizer would conclude that all rows fit on screen — rendering the whole
 * list and hiding the very regression these tests exist to catch. Pinning a
 * height makes the windowing math real: with jsdom's 768px viewport the range
 * is a handful of rows plus the overscan buffer, exactly as in a browser.
 */
const MOCK_CARD_HEIGHT = 200;
let originalOffsetHeight: PropertyDescriptor | undefined;

beforeAll(() => {
  originalOffsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get: () => MOCK_CARD_HEIGHT,
  });
});

afterAll(() => {
  if (originalOffsetHeight) {
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', originalOffsetHeight);
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, 'offsetHeight');
  }
});

function createMockJobs(count: number): Job[] {
  return Array.from({ length: count }, (_, i) => {
    const createdAt = new Date(Date.now() - i * 1000).toISOString();
    return {
      id: `job-${i}`,
      title: `Software Engineer ${i}`,
      // A REAL first-party id, not a synthetic one. `JobListingCard` resolves an
      // unrecognized id against the signed-in user's own boards, which needs a
      // Redux Provider — a dependency this list test has no reason to take on,
      // and which production never hits here (the Recent Jobs feed only fans out
      // over `COMPANIES`).
      company: 'spacex',
      location: 'Remote',
      employmentType: 'Full-time',
      createdAt,
      firstSeenAt: createdAt,
      url: `https://example.com/job-${i}`,
      department: 'Engineering',
      team: 'Backend',
      tags: [],
      isRemote: true,
      source: 'backend-scraper' as const,
      raw: {},
    };
  });
}

function mountedRowCount() {
  return screen.queryAllByRole('listitem').length;
}

/**
 * These tests hand the virtualizer the FULL array — no upstream slice — so the
 * mounted count is bounded by the virtualizer alone. (An earlier version passed
 * a pre-sliced 50-row window, which made "bounded" true no matter what the
 * component did.)
 */
describe('VirtualJobRows', () => {
  it('mounts only a viewport-sized window of a 29,000-row list', () => {
    const jobs = createMockJobs(29000);

    render(<VirtualJobRows jobs={jobs} totalCount={jobs.length} />);

    expect(mountedRowCount()).toBeGreaterThan(0);
    expect(mountedRowCount()).toBeLessThanOrEqual(60);
  });

  it('mounts the same number of rows for 100 as for 29,000 jobs', () => {
    const { unmount } = render(
      <VirtualJobRows jobs={createMockJobs(100)} totalCount={100} />
    );
    const smallListCount = mountedRowCount();
    unmount();

    render(<VirtualJobRows jobs={createMockJobs(29000)} totalCount={29000} />);

    expect(mountedRowCount()).toBe(smallListCount);
    // Sanity: the bound is the viewport + overscan, not some accident of the
    // list length.
    expect(smallListCount).toBeLessThanOrEqual(
      Math.ceil(window.innerHeight / MOCK_CARD_HEIGHT) + 2 * VIRTUAL_LIST_CONFIG.OVERSCAN + 2
    );
  });

  it('renders a spacer tall enough for every row, not just the mounted ones', () => {
    const { container } = render(
      <VirtualJobRows jobs={createMockJobs(1000)} totalCount={1000} />
    );

    const list = container.querySelector('[role="list"]') as HTMLElement;
    // 1000 rows * 200px, give or take rows still on the estimate. The height
    // arrives through an emotion class, so read the resolved value.
    const height = parseInt(window.getComputedStyle(list).height, 10);
    expect(height).toBeGreaterThan(150000);
  });

  it('advertises the FULL list length to assistive tech, not the rendered window', () => {
    // The caller passes a reveal window of 50 out of a 4,000-row list.
    render(<VirtualJobRows jobs={createMockJobs(50)} totalCount={4000} />);

    const rows = screen.getAllByRole('listitem');
    expect(rows[0]).toHaveAttribute('aria-setsize', '4000');
    expect(rows[0]).toHaveAttribute('aria-posinset', '1');
    expect(rows[1]).toHaveAttribute('aria-posinset', '2');
  });

  it('survives the row set shrinking underneath it', () => {
    // A window widening clears the cursors/floors, dropping the completeness
    // clamp, then re-applies a tighter one as the restarted pages land — so the
    // list can genuinely get SHORTER between renders while the virtualizer
    // still holds indices from the longer one.
    const { rerender, container } = render(
      <VirtualJobRows jobs={createMockJobs(1000)} totalCount={1000} />
    );
    expect(mountedRowCount()).toBeGreaterThan(0);

    expect(() =>
      rerender(<VirtualJobRows jobs={createMockJobs(3)} totalCount={3} />)
    ).not.toThrow();

    expect(mountedRowCount()).toBe(3);
    expect(container.querySelector('[role="list"]')).toHaveAttribute('data-client-window', '3');
  });

  it('renders nothing but an empty list container for an empty array', () => {
    const { container } = render(<VirtualJobRows jobs={[]} totalCount={0} />);

    expect(container.querySelector('[role="list"]')).toBeInTheDocument();
    expect(mountedRowCount()).toBe(0);
  });
});
