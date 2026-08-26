import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { DiscoveryStatus } from '../../../components/my-companies/DiscoveryStatus';
import {
  isAlreadyPublic,
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

const ALREADY_PUBLIC: AddUserCompanyResult = {
  status: 'already_public',
  detail: 'That URL is the same job board as our public Spotify page.',
  companyId: 'spotify',
  displayName: 'Spotify',
  finalUrl: 'https://jobs.lever.co/spotify',
};

describe('isDiscoveryPending', () => {
  it('discriminates the 202 discovery_pending body from a tracked UserCompany', () => {
    expect(isDiscoveryPending(PENDING)).toBe(true);
    expect(isDiscoveryPending(TRACKED)).toBe(false);
    expect(isDiscoveryPending(ALREADY_PUBLIC)).toBe(false);
  });
});

describe('isAlreadyPublic', () => {
  it('discriminates the already-published body from the other two', () => {
    expect(isAlreadyPublic(ALREADY_PUBLIC)).toBe(true);
    expect(isAlreadyPublic(TRACKED)).toBe(false);
    expect(isAlreadyPublic(PENDING)).toBe(false);
  });
});

describe('DiscoveryStatus', () => {
  it('renders no button — discovery is already running by the time this shows', () => {
    // The defect this component was reshaped to fix: a second click between the submit
    // and the one-time discovery. If a button ever comes back here, that click is back.
    renderWithProviders(<DiscoveryStatus result={undefined} error={undefined} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByTestId('discovery-starting')).toBeInTheDocument();
  });

  it('renders the one-time-setup notice for a 202 discovery_pending', () => {
    renderWithProviders(<DiscoveryStatus result={PENDING} error={undefined} />);

    expect(screen.getByTestId('discovery-pending')).toBeInTheDocument();
    expect(screen.getByText('Setting this board up')).toBeInTheDocument();
    // The server's own sentence, plus ONE line saying where to watch it. The two
    // flag-dependent variants this used to carry were two ways of saying that.
    expect(screen.getByTestId('discovery-pending')).toHaveTextContent(
      /jobs appear after the first scan\. Watch it in your list below\./,
    );
  });

  it('links to the public page when the add resolved to a board we already publish', () => {
    // Reachable when the FIRST resolve said `no_ats_detected` and the add's own
    // re-resolve then found the board. Without this branch the fall-through below
    // would read "Now tracking undefined" and link to `/add-companies/undefined`.
    renderWithProviders(<DiscoveryStatus result={ALREADY_PUBLIC} error={undefined} />);

    expect(screen.getByTestId('already-public')).toHaveTextContent(
      /we already track spotify/i,
    );
    expect(screen.getByTestId('already-public-link')).toHaveAttribute(
      'href',
      '/companies?company=spotify',
    );
    expect(screen.queryByTestId('discovery-already-tracked')).not.toBeInTheDocument();
    // This component owns no mutation, so it must not grow a button here either.
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('offers "track it separately anyway" when the parent lends it a mutation', () => {
    // WHY THIS BRANCH MATTERS NOW. This component only ever renders when the first
    // resolve said `no_ats_detected` — which is exactly what Amazon, Apple, Google,
    // Microsoft and TikTok do, since they are published with `ats='script'` and no URL
    // spells an ATS pair for them. The backend's careers-host match answers
    // `already_public` HERE, so this is where somebody who pasted Microsoft's careers
    // page lands. Without the escape hatch that is a dead end for five real companies.
    const onTrackAnyway = vi.fn();
    renderWithProviders(
      <DiscoveryStatus
        result={ALREADY_PUBLIC}
        error={undefined}
        onTrackAnyway={onTrackAnyway}
      />,
    );

    // The link is still the PRIMARY action; the escape hatch is a plain text button
    // under it, and its caption names the cost rather than leaving "anyway" bare.
    expect(screen.getByTestId('already-public-link')).toBeInTheDocument();
    const button = screen.getByTestId('track-anyway-button');
    expect(button).toHaveTextContent(/track it separately anyway/i);
    expect(screen.getByText(/its history starts today/i)).toBeInTheDocument();

    fireEvent.click(button);

    // The URL the SERVER settled on, not the one the user typed — that is what
    // `finalUrl` is on the wire for, and re-sending it is what `AddCompanyCTA` does.
    expect(onTrackAnyway).toHaveBeenCalledWith('https://jobs.lever.co/spotify');
  });

  it('disables the escape hatch while the parent add is in flight', () => {
    renderWithProviders(
      <DiscoveryStatus
        result={ALREADY_PUBLIC}
        error={undefined}
        onTrackAnyway={vi.fn()}
        isTracking
      />,
    );

    const button = screen.getByTestId('track-anyway-button');
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/adding/i);
  });

  it('renders an idempotent 200 as an already-tracked company with a link to it', () => {
    renderWithProviders(<DiscoveryStatus result={TRACKED} error={undefined} />);

    expect(screen.getByTestId('discovery-already-tracked')).toBeInTheDocument();
    expect(screen.getByText(/now tracking acme\.example/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /view its trend page/i })).toHaveAttribute(
      'href',
      '/add-companies/u-abc1234567',
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
