import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { AlreadyPublicNotice } from '../../../components/my-companies/AlreadyPublicNotice';
import type { AlreadyPublicResponse } from '../../../features/userCompanies/userCompaniesApi';

const SPOTIFY: AlreadyPublicResponse = {
  status: 'already_public',
  detail:
    'That URL is the same job board as our public Spotify page, so there is nothing to set up — its hiring trend is already there.',
  companyId: 'spotify',
  displayName: 'Spotify',
  finalUrl: 'https://jobs.lever.co/spotify',
};

describe('AlreadyPublicNotice', () => {
  it('deep-links to the public company we know about', () => {
    renderWithProviders(<AlreadyPublicNotice result={SPOTIFY} />);

    expect(screen.getByTestId('already-public')).toHaveTextContent(
      /we already track spotify/i,
    );
    const link = screen.getByTestId('already-public-link');
    expect(link).toHaveAttribute('href', '/companies?company=spotify');
    expect(link).toHaveTextContent(/see all jobs/i);
  });

  it('falls back to the trends page for a company this build has never heard of', () => {
    // The server's company list can be ahead of the shipped bundle. A deep link to an
    // id `companies.ts` does not carry is silently swallowed by `getCompanyFromURL`,
    // which falls back to the DEFAULT company — so the user would be told "here's
    // Northwind" and land on SpaceX's chart. Link to the page itself instead.
    renderWithProviders(
      <AlreadyPublicNotice
        result={{ ...SPOTIFY, companyId: 'northwind', displayName: 'Northwind' }}
      />,
    );

    const link = screen.getByTestId('already-public-link');
    expect(link).toHaveAttribute('href', '/companies');
    expect(link).toHaveTextContent(/see company hiring trends/i);
    expect(link).not.toHaveTextContent(/northwind/i);
  });

  it('renders any secondary action it is given, alongside the one-line copy', () => {
    renderWithProviders(
      <AlreadyPublicNotice result={SPOTIFY} action={<button>Do the other thing</button>} />,
    );

    expect(screen.getByTestId('already-public')).toHaveTextContent(
      /we already track spotify/i,
    );
    expect(screen.getByRole('button', { name: 'Do the other thing' })).toBeInTheDocument();
  });

  it('has no secondary action unless one is passed', () => {
    renderWithProviders(<AlreadyPublicNotice result={SPOTIFY} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  describe('the two confidence levels must not read the same', () => {
    // A board match is an exact identifier — a resolved `(ats, boardToken)` pair or a
    // careers host in our own declared table. A name match is a string we found inside a
    // domain. The headline is the one place a user actually reads that difference, so it
    // is the one place it has to show.

    it('states a board match flatly', () => {
      renderWithProviders(<AlreadyPublicNotice result={{ ...SPOTIFY, matchKind: 'board' }} />);

      expect(screen.getByTestId('already-public')).toHaveTextContent(
        /we already track spotify/i,
      );
      expect(screen.getByTestId('already-public')).not.toHaveTextContent(/looks like/i);
    });

    it('hedges a name match', () => {
      renderWithProviders(
        <AlreadyPublicNotice
          result={{
            ...SPOTIFY,
            matchKind: 'name',
            detail:
              'That web address looks like Spotify, which we already publish — we ' +
              'matched the name in the web address, not the board itself.',
            finalUrl: 'https://www.lifeatspotify.com/jobs',
          }}
        />,
      );

      expect(screen.getByTestId('already-public')).toHaveTextContent(
        /this looks like spotify, which we already track/i,
      );
      // The link is still the primary action on a guess.
      expect(screen.getByTestId('already-public-link')).toHaveAttribute(
        'href',
        '/companies?company=spotify',
      );
    });

    it('treats a missing matchKind as the stricter, exact reading', () => {
      // A server that predates the field only ever sent board matches, so silence must
      // mean "exact" — the reading that offers no way past the notice.
      renderWithProviders(<AlreadyPublicNotice result={SPOTIFY} />);

      expect(screen.getByTestId('already-public')).toHaveTextContent(
        /we already track spotify/i,
      );
      expect(screen.getByTestId('already-public')).not.toHaveTextContent(/looks like/i);
    });
  });
});
