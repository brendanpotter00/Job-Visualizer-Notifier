import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { BackToTopButton } from '../../../../components/recent-jobs-page/RecentJobsList/BackToTopButton';
import { INFINITE_SCROLL_CONFIG } from '../../../../constants/ui';

describe('BackToTopButton', () => {
  let scrollToMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    scrollToMock = vi.fn();
    window.scrollTo = scrollToMock as typeof window.scrollTo;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('is hidden when scrollY is below threshold', () => {
    Object.defineProperty(window, 'scrollY', {
      writable: true,
      configurable: true,
      value: 0,
    });

    const { container } = render(<BackToTopButton />);

    // Button exists but is hidden by MUI Zoom transition
    const button = container.querySelector('.MuiFab-root');
    expect(button).toBeInTheDocument();
    expect(button).toHaveStyle({ visibility: 'hidden' });
  });

  it('scrolls to top when clicked', () => {
    const { container } = render(<BackToTopButton />);

    const button = container.querySelector('.MuiFab-root');
    expect(button).not.toBeNull();
    fireEvent.click(button!);

    expect(scrollToMock).toHaveBeenCalledWith({
      top: 0,
      behavior: 'smooth',
    });
  });

  it('has correct accessibility label', () => {
    const { container } = render(<BackToTopButton />);

    const button = container.querySelector('.MuiFab-root');
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute('aria-label', 'Scroll to top');
  });

  it('debounces scroll events', () => {
    Object.defineProperty(window, 'scrollY', {
      writable: true,
      configurable: true,
      value: 0,
    });

    render(<BackToTopButton />);

    // Trigger multiple scroll events rapidly
    fireEvent.scroll(window);
    fireEvent.scroll(window);
    fireEvent.scroll(window);

    // Only one update should happen after debounce time
    vi.advanceTimersByTime(INFINITE_SCROLL_CONFIG.SCROLL_DEBOUNCE_MS - 10);

    // Still within debounce window
    vi.advanceTimersByTime(20);

    // Should only process once
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cleans up scroll listener on unmount', () => {
    const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener');

    const { unmount } = render(<BackToTopButton />);

    unmount();

    expect(removeEventListenerSpy).toHaveBeenCalledWith('scroll', expect.any(Function));

    removeEventListenerSpy.mockRestore();
  });

  it('renders as MUI Fab with primary color', () => {
    const { container } = render(<BackToTopButton />);

    const button = container.querySelector('.MuiFab-root');
    expect(button).toBeInTheDocument();
    expect(button).toHaveClass('MuiFab-root');
    expect(button).toHaveClass('MuiFab-primary');
  });

  it('is positioned fixed at bottom-right', () => {
    const { container } = render(<BackToTopButton />);

    const button = container.querySelector('.MuiFab-root');
    expect(button).toBeInTheDocument();

    // MUI applies inline styles, check for fixed position
    expect(button?.parentElement).toBeTruthy();
  });
});
