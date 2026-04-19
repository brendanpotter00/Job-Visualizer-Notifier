import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NewFeatureCallout } from '../../../../components/shared/NewFeatureCallout/NewFeatureCallout';

const STORAGE_KEY = 'test-callout';
const FUTURE_ISO = '2999-01-01T00:00:00Z';
const PAST_ISO = '2000-01-01T00:00:00Z';
const DISMISSED_LOCALSTORAGE_KEY = `newFeatureCallout:${STORAGE_KEY}:dismissed`;

describe('NewFeatureCallout', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders the label and a Dismiss button by default', () => {
    render(<NewFeatureCallout storageKey={STORAGE_KEY} expiresAt={FUTURE_ISO} label="New! Try it" />);
    expect(screen.getByText('New! Try it')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeInTheDocument();
  });

  it('exposes role="status" on the outer wrapper', () => {
    render(<NewFeatureCallout storageKey={STORAGE_KEY} expiresAt={FUTURE_ISO} label="Hi" />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('clicking Dismiss unmounts the callout and writes to localStorage', () => {
    render(<NewFeatureCallout storageKey={STORAGE_KEY} expiresAt={FUTURE_ISO} label="Hi" />);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByText('Hi')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Dismiss' })).not.toBeInTheDocument();
    expect(window.localStorage.getItem(DISMISSED_LOCALSTORAGE_KEY)).not.toBeNull();
  });

  it('re-rendering with the same storageKey after dismissal renders nothing', () => {
    const { unmount } = render(
      <NewFeatureCallout storageKey={STORAGE_KEY} expiresAt={FUTURE_ISO} label="Hi" />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    unmount();

    render(<NewFeatureCallout storageKey={STORAGE_KEY} expiresAt={FUTURE_ISO} label="Hi" />);
    expect(screen.queryByText('Hi')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('expired expiresAt renders null and never reads localStorage', () => {
    const getItemSpy = vi.spyOn(Storage.prototype, 'getItem');
    render(<NewFeatureCallout storageKey={STORAGE_KEY} expiresAt={PAST_ISO} label="Hi" />);
    expect(screen.queryByText('Hi')).not.toBeInTheDocument();
    expect(getItemSpy).not.toHaveBeenCalled();
  });

  it('malformed expiresAt renders null', () => {
    render(<NewFeatureCallout storageKey={STORAGE_KEY} expiresAt="not a date" label="Hi" />);
    expect(screen.queryByText('Hi')).not.toBeInTheDocument();
  });

  it('accepts a Date instance for expiresAt', () => {
    const future = new Date(Date.now() + 60_000);
    render(<NewFeatureCallout storageKey={STORAGE_KEY} expiresAt={future} label="Hi" />);
    expect(screen.getByText('Hi')).toBeInTheDocument();
  });

  it('invokes onClick when the body is clicked', () => {
    const onClick = vi.fn();
    render(
      <NewFeatureCallout
        storageKey={STORAGE_KEY}
        expiresAt={FUTURE_ISO}
        label="Hi"
        onClick={onClick}
      />
    );
    fireEvent.click(screen.getByText('Hi'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('does NOT invoke onClick when Dismiss is clicked (stopPropagation)', () => {
    const onClick = vi.fn();
    render(
      <NewFeatureCallout
        storageKey={STORAGE_KEY}
        expiresAt={FUTURE_ISO}
        label="Hi"
        onClick={onClick}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it('does not render the body as a button when onClick is omitted', () => {
    render(<NewFeatureCallout storageKey={STORAGE_KEY} expiresAt={FUTURE_ISO} label="Hi" />);
    expect(screen.getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeInTheDocument();
  });

  it('seeds dismissal state from localStorage on first render (no flash)', () => {
    window.localStorage.setItem(DISMISSED_LOCALSTORAGE_KEY, new Date().toISOString());
    render(<NewFeatureCallout storageKey={STORAGE_KEY} expiresAt={FUTURE_ISO} label="Hi" />);
    expect(screen.queryByText('Hi')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('forwards data-testid onto the outer wrapper', () => {
    render(
      <NewFeatureCallout
        storageKey={STORAGE_KEY}
        expiresAt={FUTURE_ISO}
        label="Hi"
        data-testid="my-pill"
      />
    );
    expect(screen.getByTestId('my-pill')).toBeInTheDocument();
  });
});
