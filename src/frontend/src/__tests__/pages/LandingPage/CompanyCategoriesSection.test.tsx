import { describe, it, expect } from 'vitest';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { createTestStore } from '../../../test/testUtils';
import { COMPANY_CATEGORIES } from '../../../config/companyCategories';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { CompanyCategoriesSection } from '../../../pages/LandingPage/sections/CompanyCategoriesSection';
import {
  addRecentJobsLocation,
  setRecentJobsLevel,
} from '../../../features/filters/slices/recentJobsFiltersSlice';

/** Mirrors `VISIBLE_LOGOS` in the section — the head slice shown per card. */
const VISIBLE_LOGOS = 6;

/** Where the router is, for asserting the SPA navigation. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

/** A stand-in Recent page with a Back control, for the Back-then-card path. */
function JobsStub() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(-1)}>
      Back
    </button>
  );
}

function renderSection(store = createTestStore()) {
  render(
    <Provider store={store}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<CompanyCategoriesSection content={LANDING_CONTENT} />} />
          <Route path="/jobs" element={<JobsStub />} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </Provider>
  );
  return store;
}

describe('CompanyCategoriesSection', () => {
  it('renders the section heading', () => {
    renderSection();
    expect(
      screen.getByRole('heading', { name: 'Curated Companies', level: 2 })
    ).toBeInTheDocument();
  });

  it('renders one card per company type, ten in all', () => {
    renderSection();
    expect(COMPANY_CATEGORIES).toHaveLength(10);
    for (const category of COMPANY_CATEGORIES) {
      expect(screen.getByRole('heading', { name: category.label, level: 3 })).toBeInTheDocument();
    }
    expect(screen.getAllByRole('link')).toHaveLength(10);
  });

  it('shows no member count and no description on the cards', () => {
    renderSection();
    expect(screen.queryByText(/\d+ companies/)).not.toBeInTheDocument();
    for (const category of COMPANY_CATEGORIES) {
      const card = screen.getByRole('link', { name: category.label });
      expect(card.querySelectorAll('p')).toHaveLength(0);
    }
  });

  it('links each card to Recent Job Postings filtered to its type', () => {
    renderSection();
    for (const category of COMPANY_CATEGORIES) {
      expect(screen.getByRole('link', { name: category.label })).toHaveAttribute(
        'href',
        `/jobs?company_type=${category.slug}`
      );
    }
  });

  it('shows the first six members in data order, each with alt text', () => {
    renderSection();
    for (const category of COMPANY_CATEGORIES) {
      const card = screen.getByRole('link', { name: category.label });
      const imgs = Array.from(card.querySelectorAll('img'));
      expect(imgs).toHaveLength(Math.min(VISIBLE_LOGOS, category.companyIds.length));
      for (const img of imgs) {
        expect(img.getAttribute('alt')?.trim()).toBeTruthy();
      }
    }
    // Big Tech leads with the giants, in the file's order.
    const bigTech = screen.getByRole('link', { name: 'Big Tech' });
    const alts = Array.from(bigTech.querySelectorAll('img')).map((img) => img.getAttribute('alt'));
    expect(alts.map((alt) => alt?.toLowerCase())).toEqual(
      ['Google', 'Apple', 'Microsoft', 'Amazon', 'Meta', 'NVIDIA'].map((name) =>
        expect.stringContaining(name.toLowerCase())
      )
    );
  });

  it('collapses the remaining members into a "+N" indicator', () => {
    renderSection();
    for (const category of COMPANY_CATEGORIES) {
      const card = screen.getByRole('link', { name: category.label });
      const overflow = category.companyIds.length - VISIBLE_LOGOS;
      if (overflow > 0) {
        expect(within(card).getByText(`+${overflow}`)).toBeInTheDocument();
      } else {
        expect(within(card).queryByText(/^\+\d+$/)).toBeNull();
      }
    }
  });

  it('a click leaves the Recent filters holding only that type, and navigates in-app', async () => {
    const store = createTestStore();
    store.dispatch(setRecentJobsLevel(['senior']));
    store.dispatch(addRecentJobsLocation('Austin, TX, US'));
    renderSection(store);
    const user = userEvent.setup();

    await user.click(screen.getByRole('link', { name: 'AI Labs' }));

    const filters = store.getState().recentJobsFilters.filters;
    expect(filters.companyCategory).toEqual(['ai_labs']);
    expect(filters.level).toBeUndefined();
    expect(filters.location).toBeUndefined();
    expect(screen.getByTestId('location')).toHaveTextContent('/jobs?company_type=ai_labs');
  });

  it('Back then another card replaces the first type', async () => {
    // `useRecentJobsUrlSync` reads the URL once per app mount, so the card has
    // to set the slice itself for a second arrival to take effect.
    const store = renderSection();
    const user = userEvent.setup();

    await user.click(screen.getByRole('link', { name: 'Big Tech' }));
    expect(store.getState().recentJobsFilters.filters.companyCategory).toEqual(['big_tech']);

    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(screen.getByRole('link', { name: 'Fintech & Trading' }));

    expect(store.getState().recentJobsFilters.filters.companyCategory).toEqual(['fintech']);
    expect(screen.getByTestId('location')).toHaveTextContent('/jobs?company_type=fintech');
  });

  it('leaves the filters alone on a modified click (new tab)', () => {
    const store = createTestStore();
    store.dispatch(setRecentJobsLevel(['senior']));
    renderSection(store);
    const card = screen.getByRole('link', { name: 'Big Tech' });

    act(() => {
      card.dispatchEvent(
        new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, metaKey: true })
      );
    });

    const filters = store.getState().recentJobsFilters.filters;
    expect(filters.companyCategory).toBeUndefined();
    expect(filters.level).toEqual(['senior']);
  });
});
