import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import React from 'react';
import { useBrowserNavigation } from '../../../app/hooks/useBrowserNavigation';
import appReducer from '../../../features/app/appSlice';
import jobsReducer from '../../../features/jobs/jobsSlice';
import graphFiltersReducer from '../../../features/filters/graphFiltersSlice';
import listFiltersReducer from '../../../features/filters/listFiltersSlice';
import uiReducer from '../../../features/ui/uiSlice';

function createTestStore(preloadedState = {}) {
  return configureStore({
    reducer: {
      app: appReducer,
      jobs: jobsReducer,
      graphFilters: graphFiltersReducer,
      listFilters: listFiltersReducer,
      ui: uiReducer,
    },
    preloadedState,
  });
}

describe('useBrowserNavigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset window.location
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/'),
      writable: true,
      configurable: true,
    });
    vi.spyOn(window, 'addEventListener');
    vi.spyOn(window, 'removeEventListener');
  });

  it('should register popstate event listener on mount', () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    expect(window.addEventListener).toHaveBeenCalledWith('popstate', expect.any(Function));
  });

  it('should remove popstate event listener on unmount', () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    const { unmount } = renderHook(() => useBrowserNavigation(), { wrapper });

    unmount();

    expect(window.removeEventListener).toHaveBeenCalledWith('popstate', expect.any(Function));
  });

  it('should update company when popstate event is triggered', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedView: 'greenhouse',
        isInitialized: true,
      },
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    // Simulate browser back/forward navigation
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/?company=anthropic'),
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
        selectedView: 'greenhouse',
        isInitialized: true,
      },
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    // Simulate popstate with same company
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/?company=spacex'),
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
        selectedView: 'greenhouse',
        isInitialized: true,
      },
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    // Simulate popstate with invalid company
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/?company=invalid'),
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
        selectedView: 'greenhouse',
        isInitialized: true,
      },
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    renderHook(() => useBrowserNavigation(), { wrapper });

    // Simulate popstate with no company parameter
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/'),
      writable: true,
      configurable: true,
    });
    window.dispatchEvent(new PopStateEvent('popstate'));

    // Company should remain the same
    expect(store.getState().app.selectedCompanyId).toBe('spacex');
  });
});
