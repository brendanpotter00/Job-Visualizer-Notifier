import { describe, it, expect, vi } from 'vitest';
import { screen, fireEvent } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { AddCompanyOutcome } from '../../../components/my-companies/AddCompanyOutcome';
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

/** The EXACT rung: a careers host in the backend's own declared table. Terminal. */
const ALREADY_PUBLIC: AddUserCompanyResult = {
  status: 'already_public',
  detail: 'That URL is the same job board as our public Spotify page.',
  companyId: 'spotify',
  displayName: 'Spotify',
  finalUrl: 'https://jobs.lever.co/spotify',
  matchKind: 'board',
};

/** The GUESSED rung: the company name read out of the domain. Keeps a way out. */
const NAME_GUESS: AddUserCompanyResult = {
  status: 'already_public',
  detail:
    'That web address looks like Spotify, which we already publish — we matched the ' +
    'name in the web address, not the board itself.',
  companyId: 'spotify',
  displayName: 'Spotify',
  finalUrl: 'https://www.lifeatspotify.com/jobs',
  matchKind: 'name',
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

describe('AddCompanyOutcome', () => {
  it('renders nothing at all before the add has answered', () => {
    // The page renders this unconditionally next to its spinner, so "no result yet"
    // has to be silence. A placeholder here would sit under the spinner claiming
    // something about a request that has not landed.
    const { container } = renderWithProviders(
      <AddCompanyOutcome result={undefined} error={undefined} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the success card for a 201 with a link to the new trend page', () => {
    renderWithProviders(<AddCompanyOutcome result={TRACKED} error={undefined} />);

    expect(screen.getByTestId('add-company-success')).toBeInTheDocument();
    expect(screen.getByText(/now tracking acme\.example/i)).toBeInTheDocument();
    expect(screen.getByTestId('view-company-link')).toHaveAttribute(
      'href',
      '/add-companies/u-abc1234567',
    );
  });

  it('quotes no job count on the success card', () => {
    // On a fresh add `openJobCount` is 0 — the first harvest was only just enqueued —
    // so a count here would confidently report zero jobs on a board we have not read
    // yet. The list right below carries the real number the moment it lands.
    renderWithProviders(<AddCompanyOutcome result={TRACKED} error={undefined} />);
    expect(screen.getByTestId('add-company-success')).not.toHaveTextContent(/open jobs?/i);
  });

  it('offers no second button anywhere — one press is the whole flow', () => {
    // The defect this component was reshaped to fix: pressing "Add company" used to
    // open a preview whose "Track this company" button did the actual adding. If a
    // button ever comes back on a success, that second press is back with it.
    renderWithProviders(<AddCompanyOutcome result={TRACKED} error={undefined} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders the one-time-setup notice for a 202 discovery_pending', () => {
    renderWithProviders(<AddCompanyOutcome result={PENDING} error={undefined} />);

    expect(screen.getByTestId('discovery-pending')).toBeInTheDocument();
    expect(screen.getByText('Setting this board up')).toBeInTheDocument();
    // The server's own sentence, plus ONE line saying where to watch it.
    expect(screen.getByTestId('discovery-pending')).toHaveTextContent(
      /jobs appear after the first scan\. Watch it in your list below\./,
    );
  });

  it('links to the public page when the URL is a board we already publish', () => {
    renderWithProviders(<AddCompanyOutcome result={ALREADY_PUBLIC} error={undefined} />);

    expect(screen.getByTestId('already-public')).toHaveTextContent(
      /we already track spotify/i,
    );
    expect(screen.getByTestId('already-public-link')).toHaveAttribute(
      'href',
      '/companies?company=spotify',
    );
    expect(screen.queryByTestId('add-company-success')).not.toBeInTheDocument();
  });

  it('offers NO way past an exact careers-host match, even with a mutation lent', () => {
    // An `ats='script'` careers-host hit means the user pasted a board we already
    // publish, matched against our own declared table. A private duplicate re-scrapes
    // the same feed and hands them a chart whose history starts today instead of the
    // full history one click away — a strictly worse option dressed as a choice.
    const onTrackAnyway = vi.fn();
    renderWithProviders(
      <AddCompanyOutcome
        result={ALREADY_PUBLIC}
        error={undefined}
        onTrackAnyway={onTrackAnyway}
      />,
    );

    expect(screen.getByTestId('already-public-link')).toBeInTheDocument();
    expect(screen.queryByTestId('track-anyway-button')).not.toBeInTheDocument();
    expect(onTrackAnyway).not.toHaveBeenCalled();
  });

  it('offers a correction on a GUESSED name match, because that one can be wrong', () => {
    // The other half of the same rule. `matchKind: 'name'` means we matched a string
    // inside the domain (`lifeatspotify.com` → Spotify) — not a board, not a job set.
    // Its failure mode is a false positive, and a guess with no way out would hard-block
    // somebody whose company merely shares a substring with one of ours.
    const onTrackAnyway = vi.fn();
    renderWithProviders(
      <AddCompanyOutcome
        result={NAME_GUESS}
        error={undefined}
        onTrackAnyway={onTrackAnyway}
      />,
    );

    // The headline hedges — an exact match says "We already track X" flat.
    expect(screen.getByTestId('already-public')).toHaveTextContent(
      /this looks like spotify, which we already track/i,
    );
    // The link is still the PRIMARY action; the correction is a plain text button under
    // it, and it reads as correcting us rather than as opting into a duplicate.
    expect(screen.getByTestId('already-public-link')).toBeInTheDocument();
    const button = screen.getByTestId('track-anyway-button');
    expect(button).toHaveTextContent(/this isn't the same company/i);
    expect(
      screen.getByText(/set this board up as its own company/i),
    ).toBeInTheDocument();

    fireEvent.click(button);

    // The URL the SERVER settled on, not the one the user typed — that is what
    // `finalUrl` is on the wire for.
    expect(onTrackAnyway).toHaveBeenCalledWith('https://www.lifeatspotify.com/jobs');
  });

  it('shows the guessed match with no correction when no mutation is lent', () => {
    renderWithProviders(<AddCompanyOutcome result={NAME_GUESS} error={undefined} />);

    expect(screen.getByTestId('already-public')).toBeInTheDocument();
    expect(screen.queryByTestId('track-anyway-button')).not.toBeInTheDocument();
  });

  it("uses the add endpoint's own copy for its own reason codes", () => {
    renderWithProviders(
      <AddCompanyOutcome
        result={undefined}
        error={{
          status: 422,
          data: {
            reason: 'probe_failed',
            detail: 'HTTP 503 from the board.',
            finalUrl: 'https://jobs.ashbyhq.com/acme',
          },
        }}
      />,
    );

    const alert = screen.getByTestId('add-company-error');
    expect(alert).toHaveTextContent(/couldn't read that board/i);
    expect(alert).toHaveTextContent('HTTP 503 from the board.');
    // No trailing "(code: probe_failed)" — the headline already says it in English.
    expect(alert).not.toHaveTextContent(/code:/);
  });

  it('names the no-setup boards when no job board was found behind the URL', () => {
    // The shape the backend returns when `custom_company_discovery_enabled` is OFF.
    renderWithProviders(
      <AddCompanyOutcome
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

    const alert = screen.getByTestId('add-company-error');
    expect(alert).toHaveTextContent('No supported ATS board was found behind this URL.');
    // Truthful dead end with a way forward, not a spinner that never resolves.
    expect(alert).toHaveTextContent('Greenhouse');
  });

  it('gives no board advice when the refusal was the monthly cap', () => {
    // The cap is not a verdict about the BOARD. "We read Greenhouse, Ashby, … with
    // no setup at all — paste one of those instead" would send someone hunting for a
    // different URL when no URL was ever the problem.
    renderWithProviders(
      <AddCompanyOutcome
        result={undefined}
        error={{
          status: 422,
          data: {
            reason: 'monthly_limit_reached',
            detail:
              "You've used all 20 of your company adds for this month. " +
              'Your next 20 become available on 1 September.',
            finalUrl: 'https://acme.example/careers',
          },
        }}
      />,
    );

    const alert = screen.getByTestId('add-company-error');
    expect(alert).toHaveTextContent(/used this month's company adds/i);
    expect(alert).toHaveTextContent(/1 September/);
    expect(alert).not.toHaveTextContent('Greenhouse');
  });

  it("falls back to the resolver's copy for a URL-shaped refusal", () => {
    // THE REGRESSION THIS PINS. These reasons used to be answered by the separate
    // `POST /api/companies/resolve` call and rendered by `ResolveErrorDisplay`. With
    // the preview gone they arrive from the ADD call, and without the
    // `describeResolveError` fallback this alert would print the generic "we couldn't
    // add that company" plus a raw `(code: scheme_not_https)`.
    renderWithProviders(
      <AddCompanyOutcome
        result={undefined}
        error={{
          status: 422,
          data: {
            reason: 'scheme_not_https',
            detail: 'Only https:// URLs are accepted.',
            finalUrl: 'http://acme.example/careers',
          },
        }}
      />,
    );

    const alert = screen.getByTestId('add-company-error');
    expect(alert).toHaveTextContent(/must use HTTPS/i);
    expect(alert).toHaveTextContent(/https:\/\//);
  });

  it("still prints the raw code for a reason neither vocabulary knows", () => {
    // An unknown code means this build is older than the server. The headline is
    // generic there, so the code is the only thing that makes a screenshot fixable.
    renderWithProviders(
      <AddCompanyOutcome
        result={undefined}
        error={{
          status: 422,
          data: { reason: 'brand_new_reason', detail: '', finalUrl: '' },
        }}
      />,
    );

    expect(screen.getByTestId('add-company-error')).toHaveTextContent(
      /code: brand_new_reason/,
    );
  });

  it('renders the flag-off 503 as the feature being off, not as a bad URL', () => {
    renderWithProviders(
      <AddCompanyOutcome
        result={undefined}
        error={{ status: 503, data: { detail: 'Custom company sources are not enabled' } }}
      />,
    );

    expect(screen.getByTestId('add-company-error')).toHaveTextContent(
      /turned off on the server/i,
    );
  });

  it('never renders [object Object] for an error with no readable message', () => {
    renderWithProviders(<AddCompanyOutcome result={undefined} error={{ status: 500 }} />);

    const alert = screen.getByTestId('add-company-error');
    expect(alert.textContent).not.toContain('[object Object]');
    expect(alert.textContent).not.toContain('undefined');
    expect(alert.textContent?.trim().length).toBeGreaterThan(0);
  });
});
