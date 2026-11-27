import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import type { User } from '../../../features/auth/authService';
import type {
  CompleteOnboardingArgs,
  OnboardingResult,
} from '../../../features/savedFilters/savedFiltersApi';

const { authState, userState, completeMock } = vi.hoisted(() => ({
  authState: { isAuthenticated: true },
  userState: { initial: null as unknown, setUserCalls: [] as unknown[] },
  completeMock: vi.fn(),
}));

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: authState.isAuthenticated,
    isLoading: false,
    user: undefined,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(async () => 'token'),
  }),
}));

// A real piece of state, so the gate's local stamp update closes the questions
// exactly as it does in the app.
vi.mock('../../../features/auth/useCurrentUser', async () => {
  const { useState } = await import('react');
  return {
    useCurrentUser: () => {
      const [user, setUserState] = useState(userState.initial as User | null);
      const setUser = (next: unknown) => {
        userState.setUserCalls.push(next);
        setUserState(next as User | null);
      };
      return { user, setUser, loading: false, error: null, reload: vi.fn() };
    },
  };
});

vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useCompleteOnboardingMutation: () => [completeMock, { isLoading: false }],
  };
});

const { OnboardingGate } = await import('../../../components/onboarding/OnboardingGate');

function makeUser(onboardingCompletedAt: string | null | undefined): User {
  const user: User = {
    id: 'u1',
    providerSubject: 'auth0|u1',
    email: 'new@example.com',
    displayName: null,
    givenName: null,
    familyName: null,
    pictureUrl: null,
    createdAt: '2026-11-22T10:00:00Z',
    updatedAt: '2026-11-22T10:00:00Z',
    isAdmin: false,
  };
  if (onboardingCompletedAt !== undefined) user.onboardingCompletedAt = onboardingCompletedAt;
  return user;
}

const STAMP = '2026-11-22T10:05:00+00:00';

function respondWithBody() {
  completeMock.mockImplementation((body: CompleteOnboardingArgs) => ({
    unwrap: () =>
      Promise.resolve<OnboardingResult>({
        onboardingCompletedAt: STAMP,
        savedFilters: {
          recentTimeWindow: 'all',
          trendTimeWindow: '90d',
          locations: body.locations,
          category: body.category,
          level: body.level,
          subcategory: body.subcategory,
          recentActiveKeywordListId: null,
          trendActiveKeywordListId: null,
        },
      }),
  }));
}

function renderGate(path = '/jobs') {
  return renderWithProviders(<OnboardingGate />, { initialEntries: [path] });
}

const questions = () => screen.queryByRole('dialog', { name: 'What roles are you looking for?' });

beforeEach(() => {
  authState.isAuthenticated = true;
  userState.initial = makeUser(null);
  userState.setUserCalls = [];
  completeMock.mockReset();
  respondWithBody();
});

describe('OnboardingGate — when the questions open', () => {
  it('opens for a signed-in user whose stamp is null', async () => {
    renderGate();
    expect(await screen.findByRole('dialog', { name: 'What roles are you looking for?' })).toBeVisible();
  });

  it('never opens for an undefined stamp (an older backend)', () => {
    userState.initial = makeUser(undefined);
    renderGate();
    expect(questions()).toBeNull();
  });

  it('never opens for an account that already has a stamp', () => {
    userState.initial = makeUser('2026-01-01T00:00:00Z');
    renderGate();
    expect(questions()).toBeNull();
  });

  it('never opens while the user is still loading', () => {
    userState.initial = null;
    renderGate();
    expect(questions()).toBeNull();
  });

  it('never opens for a signed-out visitor', () => {
    authState.isAuthenticated = false;
    renderGate();
    expect(questions()).toBeNull();
  });

  it.each(['/', '/pricing', '/pricing/'])('never opens on %s', (path) => {
    renderGate(path);
    expect(questions()).toBeNull();
  });
});

describe('OnboardingGate — after the questions', () => {
  it('stamps the user locally, closes, and shows the "Saved filters" toast once there are answers', async () => {
    const user = userEvent.setup();
    renderGate('/companies');
    await screen.findByRole('dialog');
    await user.click(screen.getByRole('checkbox', { name: 'Growth' }));
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await user.click(screen.getByRole('button', { name: 'Show my jobs' }));

    const link = await screen.findByRole('link', { name: 'Saved filters' });
    expect(link).toHaveAttribute('href', '/saved-filters');
    await waitFor(() => expect(questions()).toBeNull());

    // The stamp came from the response; no refetch of /api/users.
    const calls = userState.setUserCalls;
    const update = calls[calls.length - 1] as (u: User | null) => User | null;
    expect(update(makeUser(null))?.onboardingCompletedAt).toBe(STAMP);
    // Spoken once, by the polite live region.
    expect(screen.getByText('Saved as your filters.')).toBeInTheDocument();
  });

  it('closes with no toast when nothing was answered', async () => {
    const user = userEvent.setup();
    renderGate();
    await screen.findByRole('dialog');
    await user.click(screen.getByRole('button', { name: 'Skip' }));

    await waitFor(() => expect(questions()).toBeNull());
    expect(completeMock.mock.calls[0][0]).toMatchObject({ skipped: true });
    expect(screen.queryByRole('link', { name: 'Saved filters' })).toBeNull();
    expect(screen.queryByText('Saved as your filters.')).toBeNull();
  });

  it('closes for this visit, unstamped, when a Skip fails to save', async () => {
    completeMock.mockImplementationOnce(() => ({
      unwrap: () => Promise.reject({ status: 500, data: { detail: 'Failed to save onboarding' } }),
    }));
    const user = userEvent.setup();
    renderGate();
    await screen.findByRole('dialog');
    await user.click(screen.getByRole('button', { name: 'Skip' }));

    await waitFor(() => expect(questions()).toBeNull());
    expect(userState.setUserCalls).toHaveLength(0);
    expect(screen.queryByRole('link', { name: 'Saved filters' })).toBeNull();
  });

  it('Skip with an answer still shows the toast (Skip keeps the answers)', async () => {
    const user = userEvent.setup();
    renderGate();
    await screen.findByRole('dialog');
    await user.click(screen.getByRole('checkbox', { name: 'Data Scientist' }));
    await user.keyboard('{Escape}');

    expect(await screen.findByRole('link', { name: 'Saved filters' })).toBeInTheDocument();
    expect(completeMock.mock.calls[0][0]).toMatchObject({
      category: ['data_scientist'],
      skipped: true,
    });
  });
});
