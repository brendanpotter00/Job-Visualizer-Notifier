import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { createTestStore, renderWithProviders } from '../../../test/testUtils';
import { jobsApi } from '../../../features/jobs/jobsApi';
import { SubcategoryRevealProvider } from '../../../features/settings/subcategoryReveal';
import {
  savedFiltersApi,
  type CompleteOnboardingArgs,
  type OnboardingResult,
} from '../../../features/savedFilters/savedFiltersApi';
import {
  FALLBACK_CATEGORIES,
  FALLBACK_LEVELS,
  FALLBACK_SUBCATEGORIES,
} from '../../../constants/enrichment';
import type { SavedFilters } from '../../../types';

const { completeMock, searchMock } = vi.hoisted(() => ({
  completeMock: vi.fn(),
  searchMock: vi.fn(),
}));

vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useCompleteOnboardingMutation: () => [completeMock, { isLoading: false }],
  };
});

// Keep the real `locationsApi` (its reducer/middleware are in the store) but
// answer the search hook from the test.
vi.mock('../../../features/locations/locationsApi', async (importActual) => {
  const actual =
    await importActual<typeof import('../../../features/locations/locationsApi')>();
  return { ...actual, useSearchLocationsQuery: (...args: unknown[]) => searchMock(...args) };
});

const { OnboardingFlow } = await import('../../../components/onboarding/OnboardingFlow');

const BOSTON = {
  id: 7,
  canonicalName: 'Boston, MA, US',
  kind: 'city',
  city: 'Boston',
  region: 'MA',
  country: 'US',
  remoteScope: null,
};

function savedFrom(body: CompleteOnboardingArgs): SavedFilters {
  return {
    recentTimeWindow: 'all',
    trendTimeWindow: '90d',
    locations: body.locations,
    category: body.category,
    level: body.level,
    subcategory: body.subcategory,
    recentActiveKeywordListId: null,
    trendActiveKeywordListId: null,
  };
}

/** The mutation echoes the body back as the saved filters, like the server. */
function resolveWithBody() {
  completeMock.mockImplementation((body: CompleteOnboardingArgs) => ({
    unwrap: () =>
      Promise.resolve<OnboardingResult>({
        onboardingCompletedAt: '2026-11-22T10:00:00+00:00',
        savedFilters: savedFrom(body),
      }),
  }));
}

function PathProbe() {
  return <div data-testid="path">{useLocation().pathname}</div>;
}

async function renderFlow({ reveal = true }: { reveal?: boolean } = {}) {
  const onDone = vi.fn<(result: OnboardingResult) => void>();
  const store = createTestStore();
  await store.dispatch(
    jobsApi.util.upsertQueryData('getFacets', undefined, {
      categories: FALLBACK_CATEGORIES,
      levels: FALLBACK_LEVELS,
      subcategories: FALLBACK_SUBCATEGORIES,
    })
  );
  await store.dispatch(
    jobsApi.util.upsertQueryData('getPublicSettings', undefined, {
      sweSubcategoriesEnabled: reveal,
    })
  );
  const user = userEvent.setup();
  const view = renderWithProviders(
    <SubcategoryRevealProvider>
      <OnboardingFlow open onDone={onDone} onExited={vi.fn()} />
      <PathProbe />
    </SubcategoryRevealProvider>,
    { store, initialEntries: ['/companies'] }
  );
  return { ...view, store, user, onDone };
}

const heading = () => screen.getByRole('heading', { level: 1 });
const continueButton = () => screen.getByRole('button', { name: 'Continue' });
const backButton = () => screen.getByRole('button', { name: 'Back' });

beforeEach(() => {
  completeMock.mockReset();
  resolveWithBody();
  searchMock.mockReset();
  searchMock.mockImplementation(({ q }: { q: string }) => ({
    data: q.toLowerCase().startsWith('bos') ? [BOSTON] : [],
    isFetching: false,
    isError: false,
    error: undefined,
  }));
});

describe('OnboardingFlow — the screens', () => {
  it('is a full-screen dialog named by the question, with no subtitle', async () => {
    await renderFlow();
    const dialog = await screen.findByRole('dialog', { name: 'What roles are you looking for?' });
    expect(heading()).toHaveTextContent('What roles are you looking for?');
    // The visible counter is decorative; screen readers hear the long form.
    expect(within(dialog).getByText('1/3')).toHaveAttribute('aria-hidden', 'true');
    expect(within(dialog).getByText('Question 1 of 3')).toBeInTheDocument();
    expect(heading()).toHaveAccessibleDescription('Question 1 of 3');
    // The legend holds only the question: no hint line under it.
    expect(heading().parentElement?.tagName).toBe('LEGEND');
    expect(heading().parentElement?.textContent).toBe('What roles are you looking for?');
  });

  it('shows Back but disables it on question 1, and enables it after', async () => {
    const { user } = await renderFlow();
    expect(backButton()).toBeVisible();
    expect(backButton()).toBeDisabled();
    await user.click(continueButton());
    expect(backButton()).toBeEnabled();
    expect(heading()).toHaveTextContent('Which levels fit you?');
  });

  it('moves focus to the question on every step and names the step in the tab title', async () => {
    const { user } = await renderFlow();
    await waitFor(() => expect(heading()).toHaveFocus());
    expect(document.title).toBe('Question 1 of 3: Roles | onesecondswe');

    await user.click(continueButton());
    await waitFor(() => expect(heading()).toHaveFocus());
    expect(heading()).toHaveTextContent('Which levels fit you?');
    expect(document.title).toBe('Question 2 of 3: Levels | onesecondswe');

    await user.click(continueButton());
    await waitFor(() => expect(heading()).toHaveFocus());
    expect(heading()).toHaveTextContent('Where do you want to work?');
    expect(document.title).toBe('Question 3 of 3: Places | onesecondswe');
    expect(screen.getByRole('button', { name: 'Show my jobs' })).toBeInTheDocument();

    await user.click(backButton());
    await waitFor(() => expect(heading()).toHaveFocus());
    expect(heading()).toHaveTextContent('Which levels fit you?');
  });

  it('fills the progress bar one third per question', async () => {
    const { user } = await renderFlow();
    const fill = () => screen.getByTestId('onboarding-progress-fill');
    expect(screen.getByTestId('onboarding-progress')).toHaveAttribute('aria-hidden', 'true');
    expect(getComputedStyle(fill()).width).toBe('33.33%');
    await user.click(continueButton());
    expect(getComputedStyle(fill()).width).toBe('66.67%');
    await user.click(continueButton());
    expect(getComputedStyle(fill()).width).toBe('100%');
  });

  it('keeps the answers when going Back', async () => {
    const { user } = await renderFlow();
    await user.click(continueButton());
    await user.click(screen.getByRole('checkbox', { name: 'Entry' }));
    await user.click(continueButton());
    await user.click(backButton());
    expect(screen.getByRole('checkbox', { name: 'Entry' })).toBeChecked();
    await user.click(backButton());
    await user.click(continueButton());
    expect(screen.getByRole('checkbox', { name: 'Entry' })).toBeChecked();
  });

  it('keeps a chip the same width picked or not (the check replaces left padding)', async () => {
    const { user } = await renderFlow();
    await user.click(continueButton());
    const chip = screen.getByRole('checkbox', { name: 'Mid' }).closest('label')!;
    expect(getComputedStyle(chip).paddingLeft).toBe('24px');
    expect(getComputedStyle(chip).paddingRight).toBe('24px');
    await user.click(screen.getByRole('checkbox', { name: 'Mid' }));
    // 8px + the 12px check + the 4px gap = the 24px it had.
    expect(getComputedStyle(chip).paddingLeft).toBe('8px');
    expect(getComputedStyle(chip).paddingRight).toBe('24px');
  });
});

describe('OnboardingFlow — Software Engineering opens its specialties', () => {
  it('names the count in the label and shows only a chevron', async () => {
    await renderFlow();
    const swe = screen.getByRole('checkbox', { name: 'Software Engineering, 17 specialties' });
    expect(swe).not.toBeChecked();
    expect(screen.getByTestId('swe-chevron')).toHaveTextContent('');
    expect(screen.queryByRole('group', { name: /specialties/ })).toBeNull();
  });

  it('reveals the specialties in place when checked, and clears them when unchecked', async () => {
    const { user } = await renderFlow();
    const swe = screen.getByRole('checkbox', { name: 'Software Engineering, 17 specialties' });
    await user.click(swe);

    // The legend reads "Select for more specific roles" with a visually hidden
    // "Software Engineering specialties. " before it. (jsdom's name computation
    // drops the space a browser keeps, hence the optional \s.)
    const group = screen.getByRole('group', {
      name: /^Software Engineering specialties\.\s?Select for more specific roles$/,
    });
    expect(within(group).getByText('Select for more specific roles', { exact: false })).toBeVisible();
    expect(within(group).getAllByRole('checkbox')).toHaveLength(17);
    expect(swe).toHaveAttribute('aria-controls', group.parentElement?.id);
    expect(screen.getByText('17 specialties shown under Software Engineering.')).toBeInTheDocument();

    await user.click(within(group).getByRole('checkbox', { name: 'Backend' }));
    expect(within(group).getByRole('checkbox', { name: 'Backend' })).toBeChecked();

    await user.click(swe);
    expect(screen.queryByRole('group', { name: /specialties/ })).toBeNull();
    expect(screen.getByText('Specialties hidden.')).toBeInTheDocument();

    // Re-opening shows the specialties cleared.
    await user.click(swe);
    expect(screen.getByRole('checkbox', { name: 'Backend' })).not.toBeChecked();
  });

  it('other roles do not open anything', async () => {
    const { user } = await renderFlow();
    await user.click(screen.getByRole('checkbox', { name: 'Business Ops' }));
    expect(screen.queryByRole('group', { name: /specialties/ })).toBeNull();
  });

  it('is a plain row when the reveal flag is off', async () => {
    const { user } = await renderFlow({ reveal: false });
    const swe = screen.getByRole('checkbox', { name: 'Software Engineering' });
    expect(screen.queryByTestId('swe-chevron')).toBeNull();
    await user.click(swe);
    expect(screen.queryByRole('group', { name: /specialties/ })).toBeNull();
  });
});

describe('OnboardingFlow — saving', () => {
  it('sends every answer in one request: roles, specialties, levels, presets and a searched place', async () => {
    const { user, onDone } = await renderFlow();
    await user.click(screen.getByRole('checkbox', { name: 'Software Engineering, 17 specialties' }));
    await user.click(screen.getByRole('checkbox', { name: 'Backend' }));
    await user.click(screen.getByRole('checkbox', { name: 'Product Manager' }));
    await user.click(continueButton());

    await user.click(screen.getByRole('checkbox', { name: 'Entry' }));
    await user.click(screen.getByRole('checkbox', { name: 'New Grad' }));
    await user.click(continueButton());

    // Presets drop the ", US" suffix on screen and keep the canonical name.
    await user.click(screen.getByRole('checkbox', { name: 'San Francisco, CA' }));
    await user.click(screen.getByRole('checkbox', { name: 'Remote (US)' }));
    expect(screen.getByRole('checkbox', { name: 'United States' })).not.toBeChecked();

    const search = screen.getByRole('combobox', { name: 'Search for another place' });
    expect(search).toHaveAttribute('placeholder', 'City, state or country');
    await user.type(search, 'bos');
    await user.click(await screen.findByRole('option', { name: 'Boston, MA' }));
    // The pick becomes a chip after the presets, already picked.
    expect(screen.getByRole('checkbox', { name: 'Boston, MA' })).toBeChecked();
    expect(screen.getByText('Boston, MA added.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Show my jobs' }));

    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1));
    expect(completeMock).toHaveBeenCalledWith({
      category: ['software_engineering', 'product_manager'],
      subcategory: ['backend'],
      level: ['new_grad', 'entry'],
      locations: ['San Francisco, CA, US', 'Remote (US)', 'Boston, MA, US'],
      skipped: false,
      step: 3,
      sessionId: undefined,
    });
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
  });

  it('never waits for an answer: Continue through an empty flow saves empty lists', async () => {
    const { user } = await renderFlow();
    await user.click(continueButton());
    await user.click(continueButton());
    await user.click(screen.getByRole('button', { name: 'Show my jobs' }));
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1));
    expect(completeMock.mock.calls[0][0]).toMatchObject({
      category: [],
      subcategory: [],
      level: [],
      locations: [],
      skipped: false,
    });
  });

  it('treats Escape as Skip, keeping the answers given so far', async () => {
    const { user } = await renderFlow();
    await user.click(screen.getByRole('checkbox', { name: 'Growth' }));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1));
    expect(completeMock.mock.calls[0][0]).toMatchObject({
      category: ['growth'],
      skipped: true,
      step: 1,
    });
  });

  it('Skip sends the answers with skipped: true from any step', async () => {
    const { user } = await renderFlow();
    await user.click(continueButton());
    await user.click(screen.getByRole('checkbox', { name: 'Senior' }));
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1));
    expect(completeMock.mock.calls[0][0]).toMatchObject({
      level: ['senior'],
      skipped: true,
      step: 2,
    });
  });

  it('drops the specialties when Software Engineering is not picked', async () => {
    const { user } = await renderFlow();
    const swe = screen.getByRole('checkbox', { name: 'Software Engineering, 17 specialties' });
    await user.click(swe);
    await user.click(screen.getByRole('checkbox', { name: 'Mobile' }));
    await user.click(swe);
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1));
    expect(completeMock.mock.calls[0][0]).toMatchObject({ category: [], subcategory: [] });
  });

  it('sends one request for a double tap', async () => {
    let release: (value: OnboardingResult) => void = () => {};
    completeMock.mockImplementation(() => ({
      unwrap: () => new Promise<OnboardingResult>((resolve) => (release = resolve)),
    }));
    const { user } = await renderFlow();
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    await user.keyboard('{Escape}');
    expect(completeMock).toHaveBeenCalledTimes(1);
    release({
      onboardingCompletedAt: '2026-11-22T10:00:00+00:00',
      savedFilters: savedFrom({ ...EMPTY_BODY, skipped: true, step: 1 }),
    });
  });

  it('pushes the answers into both pages’ live filters and the saved-filters cache, then lands on Recent Job Postings', async () => {
    const { user, store, onDone } = await renderFlow();
    await user.click(screen.getByRole('checkbox', { name: 'Software Engineering, 17 specialties' }));
    await user.click(screen.getByRole('checkbox', { name: 'Backend' }));
    await user.click(continueButton());
    await user.click(screen.getByRole('checkbox', { name: 'Entry' }));
    await user.click(continueButton());
    await user.click(screen.getByRole('checkbox', { name: 'Seattle, WA' }));
    await user.click(screen.getByRole('button', { name: 'Show my jobs' }));

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    const recent = store.getState().recentJobsFilters.filters;
    expect(recent.category).toEqual(['software_engineering']);
    expect(recent.subcategory).toEqual(['backend']);
    expect(recent.level).toEqual(['entry']);
    expect(recent.location).toEqual(['Seattle, WA, US']);
    expect(recent.timeWindow).toBe('all');
    const graph = store.getState().graphFilters.filters;
    expect(graph.category).toEqual(['software_engineering']);
    expect(graph.level).toEqual(['entry']);
    expect(graph.timeWindow).toBe('90d');

    const cached = savedFiltersApi.endpoints.getSavedFilters.select()(store.getState()).data;
    expect(cached?.category).toEqual(['software_engineering']);
    expect(cached?.locations).toEqual(['Seattle, WA, US']);

    expect(screen.getByTestId('path')).toHaveTextContent('/jobs');
    expect(onDone.mock.calls[0][0]).toMatchObject({
      onboardingCompletedAt: '2026-11-22T10:00:00+00:00',
    });
  });

  it('shows the error and stays open when saving fails, then retries', async () => {
    completeMock.mockImplementationOnce(() => ({
      unwrap: () => Promise.reject({ status: 500, data: { detail: 'Failed to save onboarding' } }),
    }));
    const { user, onDone } = await renderFlow();
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    expect(await screen.findByText('Failed to save onboarding')).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Skip' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(completeMock).toHaveBeenCalledTimes(2);
  });
});

const EMPTY_BODY = { category: [], subcategory: [], level: [], locations: [] };
