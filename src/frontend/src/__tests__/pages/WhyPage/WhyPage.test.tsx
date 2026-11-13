import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { WhyPage } from '../../../pages/WhyPage/WhyPage';

describe('WhyPage', () => {
  it('renders the "Why This Was Built" h1 heading', () => {
    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    expect(
      screen.getByRole('heading', { name: /Why This Was Built/i, level: 1 })
    ).toBeInTheDocument();
  });

  it('links out to reach the author', () => {
    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    const link = screen.getByRole('link', { name: /Reach out to Brendan Potter/i });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders no Supported Companies section', () => {
    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    expect(screen.queryByRole('heading', { name: /Supported Companies/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/We currently track/i)).not.toBeInTheDocument();
    expect(screen.getAllByRole('heading')).toHaveLength(1);
  });
});
