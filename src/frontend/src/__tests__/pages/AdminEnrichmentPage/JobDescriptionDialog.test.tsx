import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JobDescriptionDialog } from '../../../pages/AdminEnrichmentPage/components/JobDescriptionDialog';
import type { EnrichmentNeedsHumanRow } from '../../../features/admin/adminApi';

// The dialog is a pure props-driven component (no RTK Query / store), so we
// render it directly with a fixture row — matching the FeedbackTable test idiom.
const BASE_ROW: EnrichmentNeedsHumanRow = {
  sourceId: 'greenhouse_api',
  jobListingId: 'j-1',
  title: 'Growth Marketing Lead',
  company: 'acme',
  url: 'https://example.com/j-1',
  jobStatus: 'OPEN',
  enrichmentStatus: 'done',
  category: 'growth',
  level: 'mid',
  tags: ['sql'],
  cleanDescription: 'Own the growth funnel end to end.\n\nSecond paragraph with detail.',
  classifyConfidence: 0.55,
  classifyReasoning: null,
  taxonomyVersion: 'v2+abc',
  judged: true,
  judgePassed: false,
  judgeConfidence: 0.5,
  judgeNotes: null,
  enrichedAt: '2026-07-09T00:00:00Z',
  humanCorrectedAt: null,
  humanCorrectedBy: null,
  humanDecision: null,
};

function makeRow(overrides: Partial<EnrichmentNeedsHumanRow> = {}): EnrichmentNeedsHumanRow {
  return { ...BASE_ROW, ...overrides };
}

describe('JobDescriptionDialog', () => {
  it('renders the full cleanDescription (title + company header) when open', () => {
    render(<JobDescriptionDialog open row={makeRow()} onClose={() => {}} />);

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Growth Marketing Lead')).toBeInTheDocument();
    expect(within(dialog).getByText('acme')).toBeInTheDocument();
    // Full (un-clamped) description, both paragraphs, is present.
    expect(
      within(dialog).getByText(/Own the growth funnel end to end\./)
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/Second paragraph with detail\./)).toBeInTheDocument();
  });

  it('renders nothing when there is no row', () => {
    const { container } = render(
      <JobDescriptionDialog open row={null} onClose={() => {}} />
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('exposes an "Open job posting" link with the correct href/target/rel', () => {
    render(<JobDescriptionDialog open row={makeRow()} onClose={() => {}} />);

    const link = screen.getByRole('link', { name: /open job posting/i });
    expect(link).toHaveAttribute('href', 'https://example.com/j-1');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
  });

  it('shows the muted fallback when cleanDescription is null', () => {
    render(<JobDescriptionDialog open row={makeRow({ cleanDescription: null })} onClose={() => {}} />);

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('No description available.')).toBeInTheDocument();
  });

  it('shows the muted fallback when cleanDescription is only whitespace', () => {
    render(
      <JobDescriptionDialog open row={makeRow({ cleanDescription: '   \n  ' })} onClose={() => {}} />
    );

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('No description available.')).toBeInTheDocument();
  });

  it('omits the external link when url is null', () => {
    render(<JobDescriptionDialog open row={makeRow({ url: null })} onClose={() => {}} />);

    expect(screen.queryByRole('link', { name: /open job posting/i })).not.toBeInTheDocument();
    // Close is still available so the dialog is dismissable.
    expect(screen.getByRole('button', { name: /close/i })).toBeInTheDocument();
  });

  it('calls onClose when Close is clicked', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<JobDescriptionDialog open row={makeRow()} onClose={onClose} />);

    await user.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
