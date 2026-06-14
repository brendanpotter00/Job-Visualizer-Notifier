import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FeedbackTable } from '../../../pages/AdminFeedbackPage/components/FeedbackTable';
import type { FeedbackRow } from '../../../features/admin/adminApi';

const ROWS: FeedbackRow[] = [
  {
    id: 'a',
    message: 'oldest',
    userId: 'u1',
    userEmail: 'old@example.com',
    displayName: 'Old User',
    createdAt: '2026-06-01T10:00:00Z',
  },
  {
    id: 'b',
    message: 'newest',
    userId: null,
    userEmail: null,
    displayName: null,
    createdAt: '2026-06-03T10:00:00Z',
  },
];

function bodyRowMessages(): string[] {
  const rows = screen.getAllByRole('row');
  // Drop the header row.
  return rows.slice(1).map((r) => within(r).getAllByRole('cell')[1].textContent ?? '');
}

describe('FeedbackTable', () => {
  it('renders an empty state when there are no rows', () => {
    render(<FeedbackTable feedback={[]} />);
    expect(screen.getByText(/no feedback has been submitted/i)).toBeInTheDocument();
  });

  it('defaults to newest-first and toggles sort direction on header click', async () => {
    const user = userEvent.setup();
    render(<FeedbackTable feedback={ROWS} />);

    expect(bodyRowMessages()).toEqual(['newest', 'oldest']);

    await user.click(screen.getByRole('button', { name: /submitted/i }));
    expect(bodyRowMessages()).toEqual(['oldest', 'newest']);
  });

  it('renders "Anonymous" for rows with no user identity and the name otherwise', () => {
    render(<FeedbackTable feedback={ROWS} />);
    expect(screen.getByText('Anonymous')).toBeInTheDocument();
    expect(screen.getByText('Old User')).toBeInTheDocument();
  });
});
