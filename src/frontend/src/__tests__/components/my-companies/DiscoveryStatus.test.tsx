import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { DiscoveryStatus } from '../../../components/my-companies/DiscoveryStatus';
import {
  isDiscoveryPending,
  type AddUserCompanyResult,
} from '../../../features/userCompanies/userCompaniesApi';

const PENDING: AddUserCompanyResult = {
  status: 'discovery_pending',
  detail:
    "One-time setup — we're figuring out how to read this board; jobs appear after the first scan.",
  finalUrl: 'https://acme.example/careers',
};

const TRACKED: AddUserCompanyResult = {
  id: 'u-abc1234567',
  displayName: 'acme.example',
  ats: 'discovered',
  boardToken: 'acme',
  sourceId: 'custom:u-abc1234567',
  healthState: 'unverified',
  openJobCount: 0,
  lastSuccessAt: null,
  trackingStartedAt: null,
};

describe('isDiscoveryPending', () => {
  it('discriminates the 202 discovery_pending body from a tracked UserCompany', () => {
    expect(isDiscoveryPending(PENDING)).toBe(true);
    expect(isDiscoveryPending(TRACKED)).toBe(false);
  });
});

describe('DiscoveryStatus', () => {
  it('renders no button — discovery is already running by the time this shows', () => {
    // The defect this component was reshaped to fix: a second click between "Check URL"
    // and the one-time discovery. If a button ever comes back here, that click is back.
    renderWithProviders(<DiscoveryStatus result={undefined} error={undefined} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByTestId('discovery-starting')).toBeInTheDocument();
  });

  it('renders the one-time-setup notice for a 202 discovery_pending', () => {
    renderWithProviders(<DiscoveryStatus result={PENDING} error={undefined} />);

    expect(screen.getByTestId('discovery-pending')).toBeInTheDocument();
    expect(screen.getByText('One-time setup')).toBeInTheDocument();
    expect(screen.getByText(/jobs appear after the first scan/)).toBeInTheDocument();
  });

  it('renders an idempotent 200 as an already-tracked company with a link to it', () => {
    renderWithProviders(<DiscoveryStatus result={TRACKED} error={undefined} />);

    expect(screen.getByTestId('discovery-already-tracked')).toBeInTheDocument();
    expect(screen.getByText(/now tracking acme\.example/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /view its trend page/i })).toHaveAttribute(
      'href',
      '/my-companies/u-abc1234567',
    );
  });

  it('surfaces the server message and names the no-setup boards when discovery fails', () => {
    // The shape the backend returns when `custom_company_discovery_enabled` is OFF.
    renderWithProviders(
      <DiscoveryStatus
        result={undefined}
        error={{
          status: 422,
          data: {
            reason: 'no_ats_detected',
            detail: 'No supported ATS board was found behind this URL.',
            finalUrl: 'https://acme.example/careers',
          },
        }}
      />,
    );

    const alert = screen.getByTestId('discovery-error');
    expect(alert).toHaveTextContent('No supported ATS board was found behind this URL.');
    // Truthful dead end with a way forward, not a spinner that never resolves.
    expect(alert).toHaveTextContent('Greenhouse');
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('never renders [object Object] for an error with no readable message', () => {
    renderWithProviders(<DiscoveryStatus result={undefined} error={{ status: 500 }} />);

    const alert = screen.getByTestId('discovery-error');
    expect(alert).toHaveTextContent(/couldn't be started/i);
    expect(alert.textContent).not.toContain('[object Object]');
    expect(alert.textContent).not.toContain('undefined');
  });
});
