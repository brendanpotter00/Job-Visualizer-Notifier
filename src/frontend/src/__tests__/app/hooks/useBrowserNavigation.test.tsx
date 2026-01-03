import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';
import React from 'react';
import { useBrowserNavigation } from '../../../hooks/useBrowserNavigation';
import { createTestStore } from '../../../test/testUtils';

describe('useBrowserNavigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset window.location to /companies (Companies page route)
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/companies'),
      writable: true,
      configurable: true,
    });
    vi.spyOn(window, 'addEventListener');
    vi.spyOn(window, 'removeEventListener');
  });

  it('should register popstate event listener on mount', () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    expect(window.addEventListener).toHaveBeenCalledWith('popstate', expect.any(Function));
  });

  it('should remove popstate event listener on unmount', () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    const { unmount } = renderHook(() => useBrowserNavigation(), { wrapper });

    unmount();

    expect(window.removeEventListener).toHaveBeenCalledWith('popstate', expect.any(Function));
  });

  it('should update company when popstate event is triggered', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: 'greenhouse',
        isInitialized: true,
      },
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    // Simulate browser back/forward navigation on /companies
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/companies?company=anthropic'),
      writable: true,
      configurable: true,
    });
    window.dispatchEvent(new PopStateEvent('popstate'));

    await waitFor(() => {
      expect(store.getState().app.selectedCompanyId).toBe('anthropic');
    });
  });

  it('should not update company when URL has same company', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: 'greenhouse',
        isInitialized: true,
      },
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    // Simulate popstate with same company on /companies
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/companies?company=spacex'),
      writable: true,
      configurable: true,
    });
    window.dispatchEvent(new PopStateEvent('popstate'));

    // Company should remain the same
    expect(store.getState().app.selectedCompanyId).toBe('spacex');
  });

  it('should not update company when URL has invalid company', () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: 'greenhouse',
        isInitialized: true,
      },
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    // Simulate popstate with invalid company on /companies
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/companies?company=invalid'),
      writable: true,
      configurable: true,
    });
    window.dispatchEvent(new PopStateEvent('popstate'));

    // Company should remain the same
    expect(store.getState().app.selectedCompanyId).toBe('spacex');
  });

  it('should not update company when URL has no company parameter', () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: 'greenhouse',
        isInitialized: true,
      },
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    // Simulate popstate with no company parameter on /companies
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/companies'),
      writable: true,
      configurable: true,
    });
    window.dispatchEvent(new PopStateEvent('popstate'));

    // Company should remain the same
    expect(store.getState().app.selectedCompanyId).toBe('spacex');
  });
});
