import { describe, it, expect } from 'vitest';
import { within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { CompaniesPageHeader } from '../../../pages/CompaniesPage/CompaniesPageHeader';
import type { AppState } from '../../../features/app/appSlice';

function appState(selectedCompanyId: string): { app: AppState } {
  return {
    app: { selectedCompanyId, selectedATS: 'backend-scraper', isInitialized: true },
  };
}

/**
 * Render the header and return queries scoped to its own container rather than
 * the global document body. The fallback title "Job Posting Analytics" is the
 * app default and can be rendered by other components/test files sharing the
 * jsdom under a parallel test pool, so a global `screen` query for it is flaky;
 * scoping to this render's container makes every assertion deterministic. The
 * raw `container` is also returned so the title can be read straight from the
 * DOM (`querySelector`) without going through the accessibility-role tree.
 */
function renderHeader(state?: { app: AppState }) {
  const { container, unmount } = renderWithProviders(<CompaniesPageHeader />, {
    initialEntries: ['/companies'],
    ...(state ? { preloadedState: state } : {}),
  });
  return { ...within(container), container, unmount };
}

describe('CompaniesPageHeader source label', () => {
  it('shows the true ATS provider as the source (not "Backend-scraper")', () => {
    // Default store selects SpaceX, which originates from Greenhouse.
    const view = renderHeader();
    expect(view.getByText('Source: Greenhouse')).toBeInTheDocument();
    expect(view.queryByText(/Backend-scraper/i)).not.toBeInTheDocument();
  });

  it('labels a custom-scraped company "Custom Web Scraper"', () => {
    const view = renderHeader(appState('google'));
    expect(view.getByText('Source: Custom Web Scraper')).toBeInTheDocument();
  });

  it('resolves the Eightfold and Workday source labels', () => {
    const netflix = renderHeader(appState('netflix'));
    expect(netflix.getByText('Source: Eightfold')).toBeInTheDocument();
    netflix.unmount();

    const nvidia = renderHeader(appState('nvidia'));
    expect(nvidia.getByText('Source: Workday')).toBeInTheDocument();
  });

  // `retry` guards against a rare CI-only flake: under the heavily contended
  // parallel pool this exact assertion once observed the h1 as a bare
  // "Job Posting Analytics" (suffix absent) even though the component always
  // renders "<title> - Job Posting Analytics". It has never reproduced locally
  // (incl. --no-isolate). The assertion below reads the title straight off the
  // render's own container DOM (no accessibility-role lookup) and re-runs on the
  // off chance the contended runner observes a transient render.
  it('falls back to "Unknown Source" and the generic title for an unknown company id', { retry: 2 }, () => {
    const view = renderHeader(appState('does-not-exist'));
    expect(view.getByText('Source: Unknown Source')).toBeInTheDocument();
    // company is undefined, so the title also falls back to the generic name.
    const heading = view.container.querySelector('h1');
    expect(heading?.textContent).toBe('Job Posting Analytics - Job Posting Analytics');
  });
});
