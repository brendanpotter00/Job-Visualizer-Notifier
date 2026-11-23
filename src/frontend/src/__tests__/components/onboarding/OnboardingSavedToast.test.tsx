import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import {
  OnboardingSavedToast,
  SAVED_TOAST_AUTO_HIDE_MS,
  SAVED_TOAST_RESUME_MS,
} from '../../../components/onboarding/OnboardingSavedToast';

function renderToast(onClose = vi.fn()) {
  render(
    <MemoryRouter>
      <OnboardingSavedToast open onClose={onClose} />
    </MemoryRouter>
  );
  return onClose;
}

const toast = () => screen.getByTestId('onboarding-saved-toast');

describe('OnboardingSavedToast', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('links "Saved filters" to the Saved Filters page', () => {
    renderToast();
    const link = screen.getByRole('link', { name: 'Saved filters' });
    expect(link).toHaveAttribute('href', '/saved-filters');
  });

  it('has a dismiss button that closes it', () => {
    const onClose = renderToast();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('is not an alert of its own (the gate announces it once)', () => {
    renderToast();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('hides after 6 seconds untouched', () => {
    const onClose = renderToast();
    act(() => {
      vi.advanceTimersByTime(SAVED_TOAST_AUTO_HIDE_MS - 1);
    });
    expect(onClose).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('pauses while hovered and resumes with 3 seconds when the pointer leaves', () => {
    const onClose = renderToast();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    fireEvent.mouseEnter(toast());
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseLeave(toast());
    act(() => {
      vi.advanceTimersByTime(SAVED_TOAST_RESUME_MS - 1);
    });
    expect(onClose).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('pauses while something in it has focus', () => {
    const onClose = renderToast();
    const link = screen.getByRole('link', { name: 'Saved filters' });
    act(() => {
      link.focus();
    });
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(onClose).not.toHaveBeenCalled();

    // Moving focus within the toast keeps it paused.
    act(() => {
      screen.getByRole('button', { name: 'Dismiss' }).focus();
    });
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(onClose).not.toHaveBeenCalled();

    // Leaving it resumes with the shorter timer.
    act(() => {
      (document.activeElement as HTMLElement).blur();
    });
    act(() => {
      vi.advanceTimersByTime(SAVED_TOAST_RESUME_MS);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
