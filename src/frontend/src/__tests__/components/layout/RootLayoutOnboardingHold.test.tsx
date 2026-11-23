// RootLayout holds the page until the first-sign-in decision is in.
//
// Regression for 2026-11-23 (prod account onboarding@gmail.com): a brand-new
// account landed on Recent Jobs, watched it load, and only THEN had the
// questions snap in over it, because the layout rendered the page while
// `GET /api/users` — the only thing that says "ask" — was still in flight.
//
// Oracle: what is in the document at each moment, and whether the page, when
// it first mounts, finds the questions already there. The wrong behaviour this
// rejects: any page render before the questions for an account that must be
// asked, and — the other way — holding a returning reader the browser already
// knows has answered.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import useMediaQuery from '@mui/material/useMediaQuery';
import { RootLayout } from '../../../components/layout/RootLayout';
import { CurrentUserProvider } from '../../../features/auth/CurrentUserProvider';
import { MAX_ONBOARDING_HOLD_MS } from '../../../components/onboarding/useOnboardingHold';
import { isRememberedAsAnswered } from '../../../components/onboarding/onboardingMemory';
import { createTestStore } from '../../../test/testUtils';

vi.mock('@mui/material/useMediaQuery');

const { authState, TOKEN_GETTER } = vi.hoisted(() => ({
  authState: {
    isAuthenticated: true,
    isLoading: false,
    sub: 'auth0|brand-new' as string | undefined,
  },
  TOKEN_GETTER: async () => 'token',
}));

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: authState.isAuthenticated,
    isLoading: authState.isLoading,
    user: authState.isAuthenticated ? { sub: authState.sub } : undefined,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: TOKEN_GETTER,
  }),
}));

// The questions themselves are covered by OnboardingFlow.test.tsx; here only
// WHETHER they are open matters, so a stand-in keeps the layout test focused.
vi.mock('../../../components/onboarding/OnboardingFlow', () => ({
  OnboardingFlow: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="What roles are you looking for?" /> : null,
}));

const NEW_SUBJECT = 'auth0|brand-new';
const STAMP = '2026-01-15T12:00:00+00:00';

function row(onboardingCompletedAt: string | null) {
  return {
    id: 'u1',
    providerSubject: NEW_SUBJECT,
    email: 'onboarding@example.com',
    displayName: null,
    givenName: null,
    familyName: null,
    pictureUrl: null,
    createdAt: '2026-11-23T16:07:27Z',
    updatedAt: '2026-11-23T16:07:27Z',
    isAdmin: false,
    onboardingCompletedAt,
  };
}

/** Every mount of the page records whether the questions were already open. */
let pageMounts: boolean[] = [];
function RecentJobsStandIn() {
  useEffect(() => {
    pageMounts.push(document.querySelector('[role="dialog"]') !== null);
  }, []);
  return <h1>Recent Job Postings</h1>;
}

/** `GET /api/users` answers only when the test says so; everything else 404s. */
let answerUsers: (response: Response) => void = () => {};
function installFetch() {
  const pending = new Promise<Response>((resolve) => {
    answerUsers = resolve;
  });
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url =
      typeof input === 'string' ? input : input instanceof Request ? input.url : String(input);
    if (url === '/api/users') return pending;
    return new Response(JSON.stringify({ detail: 'not in this test' }), { status: 404 });
  });
}

function app() {
  return (
    <Provider store={createTestStore()}>
      <CurrentUserProvider>
        <MemoryRouter initialEntries={['/jobs']}>
          <Routes>
            <Route element={<RootLayout />}>
              <Route path="/jobs" element={<RecentJobsStandIn />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </CurrentUserProvider>
    </Provider>
  );
}

function renderApp() {
  return render(app());
}

const page = () => screen.queryByRole('heading', { name: 'Recent Job Postings', hidden: true });
const questionsOpen = () => screen.queryByRole('dialog', { hidden: true });
const answer = async (response: Response) => {
  await act(async () => {
    answerUsers(response);
  });
};

describe('RootLayout holds the page until the first-sign-in decision is in', () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.mocked(useMediaQuery).mockReturnValue(false);
    window.localStorage.clear();
    authState.isAuthenticated = true;
    authState.isLoading = false;
    authState.sub = NEW_SUBJECT;
    pageMounts = [];
    fetchSpy = installFetch();
  });

  afterEach(() => {
    fetchSpy.mockRestore();
    vi.useRealTimers();
  });

  it('a brand-new account goes from the loading screen straight to the questions — the page never shows first', async () => {
    renderApp();

    // Undecided: nothing of the page, only the loading screen.
    expect(page()).toBeNull();
    expect(questionsOpen()).toBeNull();
    expect(screen.getByRole('progressbar', { name: 'Loading' })).toBeInTheDocument();

    await answer(new Response(JSON.stringify(row(null)), { status: 200 }));

    expect(await screen.findByRole('dialog', { hidden: true })).toBeInTheDocument();
    // The page may mount BEHIND the open questions (so it is there when they
    // close), but never before them.
    expect(pageMounts.every((questionsWereOpen) => questionsWereOpen)).toBe(true);
  });

  it('a returning account this browser has not seen is held for one round trip, then gets the page and is remembered', async () => {
    renderApp();
    expect(page()).toBeNull();

    await answer(new Response(JSON.stringify(row(STAMP)), { status: 200 }));

    expect(await screen.findByRole('heading', { name: 'Recent Job Postings' })).toBeInTheDocument();
    expect(questionsOpen()).toBeNull();
    expect(isRememberedAsAnswered(NEW_SUBJECT)).toBe(true);
  });

  it('an account this browser has seen answered is not held at all', () => {
    window.localStorage.setItem('jvn.onboardingAnswered.v1', JSON.stringify([NEW_SUBJECT]));
    renderApp();

    // GET /api/users is still in flight, and the page is already there.
    expect(screen.getByRole('heading', { name: 'Recent Job Postings' })).toBeInTheDocument();
  });

  it('another account remembered on this browser does not release the hold for this one', () => {
    window.localStorage.setItem(
      'jvn.onboardingAnswered.v1',
      JSON.stringify(['auth0|someone-else'])
    );
    renderApp();

    expect(page()).toBeNull();
  });

  it('a failed profile request releases the hold (an unknown stamp never asks, never traps)', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    renderApp();

    await answer(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }));

    expect(await screen.findByRole('heading', { name: 'Recent Job Postings' })).toBeInTheDocument();
    expect(questionsOpen()).toBeNull();
    errorSpy.mockRestore();
  });

  it(`a profile request that never answers releases the hold after ${MAX_ONBOARDING_HOLD_MS} ms`, async () => {
    vi.useFakeTimers();
    renderApp();
    expect(page()).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(MAX_ONBOARDING_HOLD_MS - 1);
    });
    expect(page()).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByRole('heading', { name: 'Recent Job Postings' })).toBeInTheDocument();
  });

  it('a signed-out reader is never held', () => {
    authState.isAuthenticated = false;
    authState.sub = undefined;
    renderApp();

    expect(screen.getByRole('heading', { name: 'Recent Job Postings' })).toBeInTheDocument();
  });

  it('a deep link while Auth0 restores a stored session is held until the answer, never painting the page first', async () => {
    window.localStorage.setItem('@@auth0spajs@@::client::audience::openid', '{}');
    authState.isAuthenticated = false;
    authState.isLoading = true;
    authState.sub = undefined;
    const { rerender } = renderApp();
    expect(page()).toBeNull();

    authState.isAuthenticated = true;
    authState.isLoading = false;
    authState.sub = NEW_SUBJECT;
    rerender(app());
    expect(page()).toBeNull();

    await answer(new Response(JSON.stringify(row(null)), { status: 200 }));

    expect(await screen.findByRole('dialog', { hidden: true })).toBeInTheDocument();
    expect(pageMounts.every((questionsWereOpen) => questionsWereOpen)).toBe(true);
  });

  it('signing in from a page already showing never swaps it for the loading screen', async () => {
    authState.isAuthenticated = false;
    authState.sub = undefined;
    const { rerender } = renderApp();
    expect(page()).toBeInTheDocument();

    authState.isAuthenticated = true;
    authState.sub = NEW_SUBJECT;
    rerender(app());

    expect(page()).toBeInTheDocument();
    expect(pageMounts).toHaveLength(1);
  });
});
