import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, waitForElementToBeRemoved } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FeedbackTable } from '../../../pages/AdminFeedbackPage/components/FeedbackTable';
import { useIsMobile } from '../../../hooks/useIsMobile';
import type { FeedbackRow } from '../../../features/admin/adminApi';

// FeedbackTable swaps the desktop table for a tappable list + modal on mobile.
// Mock the hook; default to desktop so the table-based assertions below hold.
vi.mock('../../../hooks/useIsMobile');

const ROWS: FeedbackRow[] = [
  {
    id: 'b',
    message: 'newest',
    userId: null,
    userEmail: null,
    displayName: null,
    createdAt: '2026-06-03T10:00:00Z',
  },
  {
    id: 'a',
    message: 'oldest',
    userId: 'u1',
    userEmail: 'old@example.com',
    displayName: 'Old User',
    createdAt: '2026-06-01T10:00:00Z',
  },
];

// The table is now controlled; tests override the handlers they assert on.
const baseProps = {
  feedback: ROWS,
  total: ROWS.length,
  page: 0,
  rowsPerPage: 25,
  sortDir: 'desc' as const,
  onPageChange: () => {},
  onRowsPerPageChange: () => {},
  onToggleSort: () => {},
};

function bodyRowMessages(): string[] {
  const rows = screen.getAllByRole('row');
  // Drop the header row.
  return rows.slice(1).map((r) => within(r).getAllByRole('cell')[1].textContent ?? '');
}

describe('FeedbackTable', () => {
  beforeEach(() => vi.mocked(useIsMobile).mockReturnValue(false));

  it('renders an empty state when total is zero', () => {
    render(<FeedbackTable {...baseProps} feedback={[]} total={0} />);
    expect(screen.getByText(/no feedback has been submitted/i)).toBeInTheDocument();
  });

  it('renders rows in the given (server-controlled) order without re-sorting', () => {
    render(<FeedbackTable {...baseProps} />);
    expect(bodyRowMessages()).toEqual(['newest', 'oldest']);
  });

  it('calls onToggleSort when the Submitted header is clicked', async () => {
    const user = userEvent.setup();
    const onToggleSort = vi.fn();
    render(<FeedbackTable {...baseProps} onToggleSort={onToggleSort} />);

    await user.click(screen.getByRole('button', { name: /submitted/i }));
    expect(onToggleSort).toHaveBeenCalledTimes(1);
  });

  it('calls onPageChange when the pager advances', async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(<FeedbackTable {...baseProps} total={60} onPageChange={onPageChange} />);

    await user.click(screen.getByRole('button', { name: /next page/i }));
    expect(onPageChange).toHaveBeenCalledWith(1);
  });

  it('renders "Anonymous" for rows with no user identity and the name otherwise', () => {
    render(<FeedbackTable {...baseProps} />);
    expect(screen.getByText('Anonymous')).toBeInTheDocument();
    expect(screen.getByText('Old User')).toBeInTheDocument();
  });

  describe('mobile (tappable list + modal)', () => {
    beforeEach(() => vi.mocked(useIsMobile).mockReturnValue(true));

    it('renders a tappable list instead of the wide table', () => {
      render(<FeedbackTable {...baseProps} />);
      // No data table on mobile…
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
      // …and each item is a button that opens its detail.
      expect(screen.getByRole('button', { name: /view feedback from old user/i })).toBeInTheDocument();
    });

    it('opens a modal with the full message when a row is tapped, and closes it', async () => {
      const user = userEvent.setup();
      render(<FeedbackTable {...baseProps} />);

      await user.click(screen.getByRole('button', { name: /view feedback from old user/i }));
      const dialog = screen.getByRole('dialog');
      expect(within(dialog).getByText('oldest')).toBeInTheDocument();
      expect(within(dialog).getByText('Old User')).toBeInTheDocument();

      await user.click(within(dialog).getByRole('button', { name: /close/i }));
      // MUI keeps the Dialog mounted through its exit transition — wait it out.
      await waitForElementToBeRemoved(() => screen.queryByRole('dialog'));
    });
  });
});
