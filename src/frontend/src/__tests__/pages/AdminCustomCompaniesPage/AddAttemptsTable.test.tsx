import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AddAttemptsTable } from '../../../pages/AdminCustomCompaniesPage/components/AddAttemptsTable';
import { DISCOVERY_STEP_LABELS } from '../../../components/my-companies/companyHealth';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { DELETED_BOARD_ATTEMPT, makeAttemptRow } from './fixtures';

vi.mock('../../../hooks/useIsMobile');

const baseProps = {
  attempts: [makeAttemptRow(), DELETED_BOARD_ATTEMPT],
  total: 2,
  page: 0,
  rowsPerPage: 25,
  onPageChange: () => {},
  onRowsPerPageChange: () => {},
};

describe('AddAttemptsTable', () => {
  beforeEach(() => vi.mocked(useIsMobile).mockReturnValue(false));

  it('renders one row per attempt with the outcome chip and the board URL', () => {
    render(<AddAttemptsTable {...baseProps} />);
    expect(screen.getByText('added')).toBeInTheDocument();
    expect(screen.getByText('refused')).toBeInTheDocument();
    // The scheme is stripped for the narrow column; the full URL lives in the
    // expansion.
    expect(screen.getByText('atlassian.com/company/careers/all-jobs')).toBeInTheDocument();
  });

  it('expands and collapses a row, and the expansion is hidden until asked for', async () => {
    const user = userEvent.setup();
    render(<AddAttemptsTable {...baseProps} />);

    expect(screen.queryByText('Attempt record')).not.toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'Expand attempt' })[0]);
    expect(await screen.findByText('Attempt record')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Collapse attempt' }));
    // `unmountOnExit` removes the panel outright once the collapse settles.
    await vi.waitFor(() => {
      expect(screen.queryByText('Attempt record')).not.toBeInTheDocument();
    });
  });

  it('renders the shared DISCOVERY_STEP_LABELS in the expansion, not a private copy', async () => {
    const user = userEvent.setup();
    render(<AddAttemptsTable {...baseProps} attempts={[makeAttemptRow()]} total={1} />);

    await user.click(screen.getByRole('button', { name: 'Expand attempt' }));

    for (const label of Object.values(DISCOVERY_STEP_LABELS)) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
  });

  it('degrades to the URL and the split error_detail when the company row was deleted', async () => {
    const user = userEvent.setup();
    render(<AddAttemptsTable {...baseProps} attempts={[DELETED_BOARD_ATTEMPT]} total={1} />);

    await user.click(screen.getByRole('button', { name: 'Expand attempt' }));

    expect(await screen.findByText(/No checklist stored/)).toBeInTheDocument();
    // The reason survives even though the board does not.
    expect(screen.getByText('HTTP 412 from the in-browser fetch on page 0')).toBeInTheDocument();
    expect(screen.getByText('jobs.sequoiacap.com/jobs/vanta')).toBeInTheDocument();
    expect(screen.queryByText(DISCOVERY_STEP_LABELS.open_page)).not.toBeInTheDocument();
  });

  it('shows the deleted-company chip and the measured decision time', async () => {
    const user = userEvent.setup();
    render(<AddAttemptsTable {...baseProps} attempts={[DELETED_BOARD_ATTEMPT]} total={1} />);

    await user.click(screen.getByRole('button', { name: 'Expand attempt' }));

    expect(await screen.findByText('deleted')).toBeInTheDocument();
    expect(screen.getByText('44 s')).toBeInTheDocument();
  });

  it('says "not measurable" rather than 0 when there was no preceding pending row', async () => {
    const user = userEvent.setup();
    render(
      <AddAttemptsTable
        {...baseProps}
        attempts={[makeAttemptRow({ decidedInS: null })]}
        total={1}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Expand attempt' }));
    expect(await screen.findByText('not measurable')).toBeInTheDocument();
  });

  it('renders "discovery never finished" for a stuck attempt', () => {
    render(
      <AddAttemptsTable
        {...baseProps}
        attempts={[
          makeAttemptRow({
            outcome: 'stuck',
            rawOutcome: 'discovery_pending',
            companyExists: false,
            companyDisplayName: null,
            companyLiveStatus: null,
            discoverySteps: null,
          }),
        ]}
        total={1}
      />
    );
    expect(screen.getByText('discovery never finished')).toBeInTheDocument();
    expect(screen.getByText('stuck')).toBeInTheDocument();
  });

  it('keeps the pager on mobile and opens the same detail body in a dialog', async () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    const user = userEvent.setup();
    render(<AddAttemptsTable {...baseProps} />);

    expect(screen.getByText('Rows per page:')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    await user.click(
      screen.getByRole('button', {
        name: 'View attempt for https://jobs.sequoiacap.com/jobs/vanta',
      })
    );
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Attempt record')).toBeInTheDocument();
  });
});
