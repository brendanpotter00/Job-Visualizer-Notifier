import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { store } from '../../../app/store';
import { AppContent } from '../../../components/AppLayout/AppContent';

// Mock Recharts to avoid rendering issues in tests
vi.mock('recharts', () => ({
  LineChart: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ResponsiveContainer: () => null,
  Legend: () => null,
}));

describe('AppContent', () => {
  it('should render loading indicator when isLoading is true', () => {
    render(
      <Provider store={store}>
        <AppContent isLoading={true} />
      </Provider>
    );

    const progressbar = screen.getByRole('progressbar');
    expect(progressbar).toBeInTheDocument();
  });

  it('should render content sections when isLoading is false', () => {
    const { container } = render(
      <Provider store={store}>
        <AppContent isLoading={false} />
      </Provider>
    );

    // Should not show loading indicator
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();

    // Should render main content (check for Stack component)
    const stack = container.querySelector('.MuiStack-root');
    expect(stack).toBeInTheDocument();
  });

  it('should have proper loading state layout', () => {
    const { container } = render(
      <Provider store={store}>
        <AppContent isLoading={true} />
      </Provider>
    );

    // Check for loading container with proper styling
    const loadingBox = container.querySelector('.MuiBox-root');
    expect(loadingBox).toBeInTheDocument();
  });

  it('should have proper content layout with Stack', () => {
    const { container } = render(
      <Provider store={store}>
        <AppContent isLoading={false} />
      </Provider>
    );

    // Check for Stack container
    const stack = container.querySelector('.MuiStack-root');
    expect(stack).toBeInTheDocument();
  });

  it('should toggle between loading and content states', () => {
    const { rerender } = render(
      <Provider store={store}>
        <AppContent isLoading={true} />
      </Provider>
    );

    expect(screen.getByRole('progressbar')).toBeInTheDocument();

    rerender(
      <Provider store={store}>
        <AppContent isLoading={false} />
      </Provider>
    );

    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });
});
