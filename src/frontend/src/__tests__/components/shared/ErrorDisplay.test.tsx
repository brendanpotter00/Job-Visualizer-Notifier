import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  ErrorDisplay,
  ErrorState,
  EmptyStateDisplay,
  EmptyState,
  NetworkErrorDisplay,
} from '../../../components/shared/ErrorDisplay';

describe('ErrorDisplay', () => {
  describe('card variant (default)', () => {
    it('renders the default title, message, and error icon', () => {
      render(<ErrorDisplay message="Something broke" />);
      expect(screen.getByRole('heading', { level: 5, name: 'Error' })).toBeInTheDocument();
      expect(screen.getByText('Something broke')).toBeInTheDocument();
    });

    it('renders a custom title and description', () => {
      render(
        <ErrorDisplay
          title="Network Down"
          description="Check your connection"
          message="Fetch failed"
        />
      );
      expect(screen.getByRole('heading', { level: 5, name: 'Network Down' })).toBeInTheDocument();
      expect(screen.getByText('Check your connection')).toBeInTheDocument();
      expect(screen.getByText('Fetch failed')).toBeInTheDocument();
    });

    it('does not render a retry button when onRetry is omitted', () => {
      render(<ErrorDisplay message="x" />);
      expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
    });

    it('renders a "Try Again" button that fires onRetry when clicked', async () => {
      const onRetry = vi.fn();
      render(<ErrorDisplay message="x" onRetry={onRetry} />);
      await userEvent.click(screen.getByRole('button', { name: /try again/i }));
      expect(onRetry).toHaveBeenCalledTimes(1);
    });
  });

  describe('inline variant', () => {
    it('renders an MUI alert with the message', () => {
      render(<ErrorDisplay inline message="Inline boom" />);
      expect(screen.getByRole('alert')).toHaveTextContent('Inline boom');
    });

    it('does not render a retry button when onRetry is omitted', () => {
      render(<ErrorDisplay inline message="x" />);
      expect(screen.queryByRole('button', { name: /retry/i })).toBeNull();
    });

    it('renders a "Retry" button that fires onRetry when clicked', async () => {
      const onRetry = vi.fn();
      render(<ErrorDisplay inline message="x" onRetry={onRetry} />);
      await userEvent.click(screen.getByRole('button', { name: /retry/i }));
      expect(onRetry).toHaveBeenCalledTimes(1);
    });

    it('does not render the card-variant heading in inline mode', () => {
      render(<ErrorDisplay inline message="x" />);
      expect(screen.queryByRole('heading', { name: 'Error' })).toBeNull();
    });
  });
});

describe('NetworkErrorDisplay', () => {
  it('renders the canned network error copy', () => {
    render(<NetworkErrorDisplay />);
    expect(screen.getByRole('heading', { level: 5, name: 'Network Error' })).toBeInTheDocument();
    expect(screen.getByText(/unable to connect to the server/i)).toBeInTheDocument();
  });

  it('wires onRetry through to the retry button', async () => {
    const onRetry = vi.fn();
    render(<NetworkErrorDisplay onRetry={onRetry} />);
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('EmptyStateDisplay', () => {
  it('renders default title and message', () => {
    render(<EmptyStateDisplay />);
    expect(screen.getByText('No Results')).toBeInTheDocument();
    expect(screen.getByText('No data to display')).toBeInTheDocument();
  });

  it('renders custom title, message, and icon', () => {
    render(
      <EmptyStateDisplay
        title="Nothing here"
        message="Try a different filter"
        icon={<span data-testid="custom-icon" />}
      />
    );
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
    expect(screen.getByText('Try a different filter')).toBeInTheDocument();
    expect(screen.getByTestId('custom-icon')).toBeInTheDocument();
  });
});

describe('Alias exports', () => {
  it('ErrorState is the same reference as ErrorDisplay', () => {
    expect(ErrorState).toBe(ErrorDisplay);
  });

  it('EmptyState is the same reference as EmptyStateDisplay', () => {
    expect(EmptyState).toBe(EmptyStateDisplay);
  });

  it('<ErrorState /> renders byte-identical output to <ErrorDisplay />', () => {
    const a = render(<ErrorDisplay message="x" title="T" />);
    const aHtml = a.container.innerHTML;
    a.unmount();

    const b = render(<ErrorState message="x" title="T" />);
    expect(b.container.innerHTML).toBe(aHtml);
  });

  it('<EmptyState /> renders byte-identical output to <EmptyStateDisplay />', () => {
    const a = render(<EmptyStateDisplay title="T" message="M" />);
    const aHtml = a.container.innerHTML;
    a.unmount();

    const b = render(<EmptyState title="T" message="M" />);
    expect(b.container.innerHTML).toBe(aHtml);
  });
});
