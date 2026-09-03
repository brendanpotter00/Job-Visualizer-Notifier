import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LiveScrapersTable } from '../../../pages/AdminCustomCompaniesPage/components/LiveScrapersTable';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { ORPHAN_COMPANY, makeCompanyRow } from './fixtures';

// The table swaps for a tappable card list on mobile. Mock the hook and default
// to desktop so the table-based assertions hold.
vi.mock('../../../hooks/useIsMobile');

const baseProps = {
  companies: [makeCompanyRow(), ORPHAN_COMPANY],
  total: 2,
  page: 0,
  rowsPerPage: 25,
  onPageChange: () => {},
  onRowsPerPageChange: () => {},
};

describe('LiveScrapersTable', () => {
  beforeEach(() => vi.mocked(useIsMobile).mockReturnValue(false));

  it('renders the Live and Orphan chips from the server-derived status', () => {
    render(<LiveScrapersTable {...baseProps} />);
    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.getByText('Orphan')).toBeInTheDocument();
  });

  it('names an unowned board rather than leaving the Owner cell blank', () => {
    render(<LiveScrapersTable {...baseProps} />);
    expect(screen.getByText('— no owner row —')).toBeInTheDocument();
  });

  it('falls back to the owner id when the users row is gone', () => {
    render(
      <LiveScrapersTable
        {...baseProps}
        companies={[makeCompanyRow({ ownerEmail: null, ownerDisplayName: null })]}
        total={1}
      />
    );
    expect(screen.getByText('user-1')).toBeInTheDocument();
  });

  it('labels a capped harvest "cap hit" and an uncapped one "open"', () => {
    render(<LiveScrapersTable {...baseProps} />);
    expect(screen.getByText('232')).toBeInTheDocument();
    expect(screen.getByText('open')).toBeInTheDocument();
    expect(screen.getByText('11,040')).toBeInTheDocument();
    expect(screen.getByText('cap hit')).toBeInTheDocument();
  });

  it('says "never" instead of an empty cell for a board that has never harvested', () => {
    render(
      <LiveScrapersTable
        {...baseProps}
        companies={[
          makeCompanyRow({
            lastHarvestAt: null,
            lastHarvestAgeS: null,
            recordsHarvested: null,
            liveStatus: 'never_harvested',
            liveReason: 'never harvested',
          }),
        ]}
        total={1}
      />
    );
    expect(screen.getByText('never')).toBeInTheDocument();
    expect(screen.getByText('Never harvested')).toBeInTheDocument();
  });

  it('renders pagination on desktop', () => {
    render(<LiveScrapersTable {...baseProps} />);
    expect(screen.getByText('Rows per page:')).toBeInTheDocument();
  });

  it('renders a card list AND pagination on mobile, and a tap opens the detail dialog', async () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    const user = userEvent.setup();
    render(<LiveScrapersTable {...baseProps} />);

    // An unpaginated admin table is a repo-level incident (root CLAUDE.md #7),
    // so the pager must survive the mobile swap.
    expect(screen.getByText('Rows per page:')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'View Amazon (live check)' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('no owner row')).toBeInTheDocument();
  });
});
