import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { store } from '../../../app/store';
import { AppHeader } from '../../../components/AppLayout/AppHeader';

describe('AppHeader', () => {
  it('should render with company name in title', () => {
    render(
      <Provider store={store}>
        <AppHeader companyName="SpaceX" />
      </Provider>
    );

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'SpaceX - Job Posting Analytics'
    );
  });

  it('should render company selector', () => {
    render(
      <Provider store={store}>
        <AppHeader companyName="Anthropic" />
      </Provider>
    );

    expect(screen.getByLabelText('Company')).toBeInTheDocument();
  });

  it('should render with default fallback name', () => {
    render(
      <Provider store={store}>
        <AppHeader companyName="Job Posting Analytics" />
      </Provider>
    );

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Job Posting Analytics - Job Posting Analytics'
    );
  });

  it('should have proper layout structure', () => {
    const { container } = render(
      <Provider store={store}>
        <AppHeader companyName="Notion" />
      </Provider>
    );

    // Should have a Stack container with proper spacing
    const stack = container.querySelector('.MuiStack-root');
    expect(stack).toBeInTheDocument();
  });

  it('should display different company names correctly', () => {
    const companies = ['SpaceX', 'Anthropic', 'Notion', 'Stripe', 'Palantir'];

    companies.forEach((companyName) => {
      const { unmount } = render(
        <Provider store={store}>
          <AppHeader companyName={companyName} />
        </Provider>
      );

      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        `${companyName} - Job Posting Analytics`
      );

      unmount();
    });
  });
});
