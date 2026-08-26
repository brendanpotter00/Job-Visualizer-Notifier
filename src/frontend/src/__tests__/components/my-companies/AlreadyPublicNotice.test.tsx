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
    expect(link).toHaveTextContent(/open spotify's hiring trend/i);
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
    expect(link).toHaveTextContent(/open company hiring trends/i);
    expect(link).not.toHaveTextContent(/northwind/i);
  });

  it('renders the server sentence and any secondary action it is given', () => {
    renderWithProviders(
      <AlreadyPublicNotice result={SPOTIFY} action={<button>Do the other thing</button>} />,
    );

    expect(screen.getByTestId('already-public')).toHaveTextContent(
      /its hiring trend is already there/i,
    );
    expect(screen.getByRole('button', { name: 'Do the other thing' })).toBeInTheDocument();
  });

  it('has no secondary action unless one is passed', () => {
    renderWithProviders(<AlreadyPublicNotice result={SPOTIFY} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
