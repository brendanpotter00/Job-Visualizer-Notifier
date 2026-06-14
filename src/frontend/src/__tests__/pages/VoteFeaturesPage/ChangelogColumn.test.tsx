import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChangelogColumn } from '../../../pages/VoteFeaturesPage/ChangelogColumn';

// Four entries, two tags. Sorted newest-first the order is:
// Feature One → Feature Two → Feature Three → Company One.
vi.mock('../../../config/changelog', () => {
  // 'improvement' is intentionally an option no mocked entry uses, so selecting
  // it filters the list down to zero and exercises the empty state.
  const CHANGELOG_TAGS = ['feature', 'new-companies', 'improvement'] as const;
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
      id: 'comp-1',
      title: 'Company One',
      description: 'Added a new company.',
      tags: ['new-companies'],
      date: '2026-01-10',
    },
  ];
  return { CHANGELOG, CHANGELOG_TAGS };
});

// Shrink the batch sizes so 4 entries exercise batching (2 shown, 2 hidden).
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

describe('ChangelogColumn', () => {
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

  it('renders only the initial batch on mount', () => {
    render(<ChangelogColumn />);

    expect(screen.getByText('Feature One')).toBeInTheDocument();
    expect(screen.getByText('Feature Two')).toBeInTheDocument();
    // Beyond the initial batch of 2 — not yet rendered.
    expect(screen.queryByText('Feature Three')).not.toBeInTheDocument();
    expect(screen.queryByText('Company One')).not.toBeInTheDocument();
    // End-of-list message is hidden while more remain.
    expect(screen.queryByText(/all 4 updates/i)).not.toBeInTheDocument();
  });

  it('reveals the next batch when the sentinel intersects', async () => {
    render(<ChangelogColumn />);

    await revealNextBatch();

    expect(screen.getByText('Feature One')).toBeInTheDocument();
    expect(screen.getByText('Feature Two')).toBeInTheDocument();
    expect(screen.getByText('Feature Three')).toBeInTheDocument();
    expect(screen.getByText('Company One')).toBeInTheDocument();
    // Everything shown — end-of-list message appears.
    expect(screen.getByText(/all 4 updates/i)).toBeInTheDocument();
  });

  it('renders entries newest-first once fully revealed', async () => {
    render(<ChangelogColumn />);
    await revealNextBatch();

    const titles = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);

    expect(titles).toEqual(['Feature One', 'Feature Two', 'Feature Three', 'Company One']);
  });

  it('selecting "new-companies" narrows the list to new-companies-tagged entries only', async () => {
    const user = userEvent.setup();
    render(<ChangelogColumn />);

    await user.click(screen.getByRole('combobox', { name: /tags/i }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'new-companies' }));

    expect(screen.getByText('Company One')).toBeInTheDocument();
    expect(screen.queryByText('Feature One')).not.toBeInTheDocument();
    expect(screen.queryByText('Feature Two')).not.toBeInTheDocument();
    // Only 1 entry — below the initial batch size — so the end-of-list "all N
    // updates" message must stay hidden. This locks in why the guard is
    // `!hasMore && length > INITIAL_BATCH_SIZE` and not just `!hasMore`.
    expect(screen.queryByText(/updates/i)).not.toBeInTheDocument();
  });

  it('shows the empty state when a tag matches no entries', async () => {
    const user = userEvent.setup();
    render(<ChangelogColumn />);

    // 'improvement' is an option but no mocked entry carries it.
    await user.click(screen.getByRole('combobox', { name: /tags/i }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'improvement' }));

    expect(screen.getByText('No changelog entries match the selected tags.')).toBeInTheDocument();
    // No entry cards.
    expect(screen.queryAllByRole('heading', { level: 3 })).toHaveLength(0);
    // No loading skeletons.
    expect(
      screen.queryByRole('status', { name: /loading more changelog entries/i })
    ).not.toBeInTheDocument();
    // No end-of-list message.
    expect(screen.queryByText(/updates/i)).not.toBeInTheDocument();
  });

  it('resets to the first batch when the tag filter changes', async () => {
    const user = userEvent.setup();
    render(<ChangelogColumn />);

    // Reveal everything first.
    await revealNextBatch();
    expect(screen.getByText('Feature Three')).toBeInTheDocument();
    expect(screen.getByText(/all 4 updates/i)).toBeInTheDocument();

    // Filtering to "feature" yields 3 entries but resets to the first batch (2).
    await user.click(screen.getByRole('combobox', { name: /tags/i }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'feature' }));

    expect(screen.getByText('Feature One')).toBeInTheDocument();
    expect(screen.getByText('Feature Two')).toBeInTheDocument();
    expect(screen.queryByText('Feature Three')).not.toBeInTheDocument();
    expect(screen.queryByText('Company One')).not.toBeInTheDocument();
    // More remain again — end-of-list message hidden.
    expect(screen.queryByText(/all 3 updates/i)).not.toBeInTheDocument();
  });
});
