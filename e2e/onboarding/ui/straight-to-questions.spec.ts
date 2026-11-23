// OB-U13 — a brand-new account goes STRAIGHT to the questions: the page never
// shows first.
//
// The 2026-11-23 production report (a brand-new account, onboarding@gmail.com):
// Recent Jobs showed loading for a while, never showed anything, and then the
// questions snapped in over it. Two causes, both pinned here:
//   1. the layout rendered the page while `GET /api/users` — the only thing
//      that says "ask" — was still in flight;
//   2. the page sent four identical `GET /api/users`, and Chrome runs those one
//      after another, so the gate's answer came back after three round trips.
//
// Production latency is the point, so every `GET /api/users*` here is held
// back USERS_LATENCY_MS before it reaches the backend (prod measured 1.5–3.5 s
// for a brand-new account). The timeline is recorded IN the page, on one
// clock: when the page's own h1 is first painted, when the questions are first
// in the DOM, and when the page's `GET /api/users` resolves.
//
// Mirror (the account that must NOT be held, or not for long): the
// pre-existing stamped account on a new device is held for that one answer and
// then gets the page with no questions; on the next load the browser knows it,
// and the page is painted while `GET /api/users` is still in flight.
import { expect, test } from '@playwright/test';
import type { BrowserContext, Page } from '@playwright/test';
import {
  PREEXISTING,
  RECENT_JOBS,
  dbState,
  expectNoAccountYet,
  expectQuestion,
  expectQuestionsNeverOpen,
  freshIdentity,
  openSignedIn,
  shot,
  trackUserFetches,
} from './helpers';

const USERS_LATENCY_MS = 1_500;

interface Timeline {
  /** First paint of the page's own "Recent Job Postings" h1. */
  page?: number;
  /** First time the questions dialog is in the DOM. */
  questions?: number;
  /** First time a `GET /api/users` from the page resolved. */
  usersAnswered?: number;
}

/** Slow `GET /api/users*` like production, and record the timeline in the page. */
async function instrument(context: BrowserContext): Promise<void> {
  await context.route(
    (url) => url.pathname === '/api/users' || url.pathname.startsWith('/api/users/'),
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, USERS_LATENCY_MS));
      await route.continue();
    },
  );
  await context.addInitScript(() => {
    const tl: Record<string, number> = {};
    (window as unknown as { __obTimeline: Record<string, number> }).__obTimeline = tl;
    const mark = (key: string) => {
      if (tl[key] === undefined) tl[key] = performance.now();
    };
    const realFetch = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await realFetch(input, init);
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
      if (method === 'GET' && new URL(url, location.href).pathname === '/api/users') mark('usersAnswered');
      return response;
    };
    const tick = () => {
      for (const h of Array.from(document.querySelectorAll('h1'))) {
        const box = h.getBoundingClientRect();
        if (h.textContent?.trim() === 'Recent Job Postings' && box.width > 0 && box.height > 0) mark('page');
      }
      if (document.querySelector('[role="dialog"]')) mark('questions');
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

async function timeline(page: Page): Promise<Timeline> {
  return page.evaluate(() => ({ ...(window as unknown as { __obTimeline: Timeline }).__obTimeline }));
}

test.describe('OB-U13 a brand-new account goes straight to the questions', () => {
  test('OB-U13 first sign-in: no page before the questions, one GET /api/users; a known account is not held', async ({
    browser,
  }) => {
    // --- A brand-new account, first sign-in --------------------------------
    const me = freshIdentity('OB-U13');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    await instrument(context);
    const page = await context.newPage();
    const users = trackUserFetches(page);

    await page.goto(RECENT_JOBS);
    await expectQuestion(page, 0);
    await shot(page, 'OB-U13', '01-straight-to-questions');

    const first = await timeline(page);
    expect(first.questions, 'the questions should be in the DOM').toBeDefined();
    expect(
      first.page === undefined || first.page >= (first.questions as number),
      `the page must never be painted before the questions (page h1 at ${first.page} ms, questions at ${first.questions} ms)`,
    ).toBe(true);
    // One shared request — not one per user menu / side menu / analytics / gate.
    expect(users.started(), 'one page load should send exactly ONE GET /api/users').toBe(1);
    expect(dbState(me).onboardingCompletedAt, 'nothing answered yet').toBeNull();
    await context.close();

    // --- Mirror: an account that answered long ago, on a new device ---------
    const known = await openSignedIn(browser, PREEXISTING);
    await instrument(known);
    const returning = await known.newPage();
    const returningUsers = trackUserFetches(returning);

    await returning.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(returning, returningUsers, 'a stamped account on a new device');
    const newDevice = await timeline(returning);
    expect(newDevice.usersAnswered, 'the page’s GET /api/users resolved').toBeDefined();
    expect(
      (newDevice.page as number) >= (newDevice.usersAnswered as number),
      `a new device does not know the account yet, so it waits for the one answer (page at ${newDevice.page} ms, answer at ${newDevice.usersAnswered} ms)`,
    ).toBe(true);
    expect(returningUsers.started(), 'one GET /api/users on the returning account too').toBe(1);

    // The same browser, next load: it knows this account has answered.
    returningUsers.reset();
    await returning.reload();
    await expectQuestionsNeverOpen(returning, returningUsers, 'the same account, next load');
    const nextLoad = await timeline(returning);
    expect(
      (nextLoad.page as number) < (nextLoad.usersAnswered as number),
      `a known account must not be held: the page is painted while GET /api/users is still in flight (page at ${nextLoad.page} ms, answer at ${nextLoad.usersAnswered} ms)`,
    ).toBe(true);
    await shot(returning, 'OB-U13', '02-known-account-not-held');
    await known.close();
  });
});
