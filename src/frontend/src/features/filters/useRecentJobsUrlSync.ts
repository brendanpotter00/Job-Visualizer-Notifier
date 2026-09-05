import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import { hydrateRecentJobsFilters } from './slices/recentJobsFiltersSlice';
import { buildSearchFromFilters, parseFiltersFromSearch } from './urlFilters';
import { ROUTES } from '../../config/routes';

/**
 * Two-way binding between the Recent page's filters and the browser URL.
 *
 * ROUTE-SCOPED, like `useURLSync` is for the mirror case (`app/hooks.ts` — "only
 * runs on the Companies page to prevent company query params from appearing on
 * other pages"). This hook is mounted at the app ROOT so it can beat
 * `useHydrateSavedFilters` to the slice, which means without the scope its write
 * would stamp `?time=…&category=…&tag=…` onto `/companies`, `/account`,
 * `/saved-filters` and every admin page. That is not cosmetic: any non-Recent
 * link a signed-in reader copies would carry their private filter set, and the
 * recipient's Recent page would ADOPT it, because a URL beats their own saved
 * filters. It is the cross-contamination `buildSearchFromFilters` deliberately
 * avoids for `company`, reintroduced globally. `/` is the index route, so the
 * match is an exact pathname equality and not a prefix — a prefix would be every
 * route in the app.
 *
 * READ (once per arrival on the Recent page): if the URL carries filter params,
 * hydrate the slice from them. Because `hydrateRecentJobsFilters` is one-shot —
 * guarded by the slice's own `hydrated` flag — doing this BEFORE the
 * saved-filters request resolves makes the later `useHydrateSavedFilters`
 * dispatch a no-op. That is the whole implementation of "a shared URL wins for
 * that visit": the reader's saved filters are never read into the page and never
 * written to, so their own set is intact on their next normal visit. No new
 * precedence mechanism, no flag to keep in sync — the guard that already existed
 * does it.
 *
 * The read is synchronous on mount while saved filters need a round trip, and
 * this hook is declared BEFORE `useHydrateSavedFilters` in `app/App.tsx`, so the
 * URL is in the slice before the request that would compete with it is even
 * dispatched. Those two facts ARE the precedence — there is no third mechanism,
 * and in particular nothing here can make a URL win once something else has
 * hydrated the slice, because `hydrate` returns early in that case and the URL
 * values are dropped on the floor. (An earlier revision followed the dispatch
 * with `setRecentJobsHydrated(true)` and a comment claiming it kept the URL
 * winning in exactly that scenario. It cannot: by then the payload has already
 * been discarded, and re-asserting a flag that is already true changes nothing.)
 *
 * WRITE: `replaceState`, not `pushState`. The address bar should always match
 * what you are looking at so copying it just works, but a filter tweak is not a
 * navigation — with `pushState`, Back would step backwards through every
 * intermediate filter state (and the 300ms debounce means there are more of
 * those than the reader made) instead of leaving the page. Chosen with the repo
 * owner.
 */
export function useRecentJobsUrlSync(): void {
  const dispatch = useAppDispatch();
  const filters = useAppSelector((state) => state.recentJobsFilters.filters);
  const hydrated = useAppSelector((state) => state.recentJobsFilters.hydrated);
  const { pathname } = useLocation();

  const isRecentJobsPage = pathname === ROUTES.RECENT_JOBS;

  /**
   * Did the address bar carry filter params when this visit reached the Recent
   * page? Recorded by the READ effect, which runs BEFORE the write effect in the
   * same commit — so the write below always sees it, and it can never be a stale
   * answer from some earlier route.
   *
   * The old version of this ref was assigned and never read, under a comment
   * claiming it stopped the write effect mistaking its own output for an
   * incoming link. Nothing implemented that. It is load-bearing now, and for a
   * different reason: see the write effect's gate.
   */
  // LIFETIME NOTE, because two reviewers read more into these than they do:
  // both refs latch once per MOUNT, not once per arrival. This hook is mounted
  // at the app root and never unmounts, so a SECOND SPA-internal arrival at `/`
  // carrying new params would be discarded and then overwritten by the in-memory
  // filters. That is unreachable today — every in-app route to `/` is a bare
  // path (`GlobalAppBar`, `NavigationDrawer`, `AdminRoute`), so params can only
  // arrive via a full page load, which remounts. Recorded rather than guarded
  // because a guard for an unreachable case is a guard nothing tests.
  const arrivalHadParams = useRef<boolean | null>(null);

  /** Set once the READ effect has had its turn on this route. */
  const arrivalUrlRead = useRef(false);

  /**
   * Set once the address bar holds nothing this hook has not already consumed.
   * MONOTONIC on purpose — see the write effect.
   */
  const mayWrite = useRef(false);

  // READ — once, as early as possible.
  useEffect(() => {
    if (!isRecentJobsPage || arrivalUrlRead.current) return;
    arrivalUrlRead.current = true;
    const fromUrl = parseFiltersFromSearch(window.location.search);
    arrivalHadParams.current = fromUrl !== null;
    if (fromUrl) dispatch(hydrateRecentJobsFilters(fromUrl));
    // Once per arrival on this route, never again: re-reading later would feed
    // this hook's own `replaceState` output back in as if it were an incoming
    // shared link, and on a slice that is not yet hydrated that would flip
    // `hydrated` and lock the reader out of their own saved filters.
    // `window.location` is not reactive, so this dep list is complete and no lint
    // suppression is needed — src/frontend/CLAUDE.md forbids new eslint-disable
    // directives.
  }, [dispatch, isRecentJobsPage]);

  // WRITE — mirror filter state into the address bar.
  useEffect(() => {
    if (!isRecentJobsPage) return;

    // THE GATE, and it is deliberately not the slice's `hydrated` flag.
    //
    // What the write must wait for is not "saved filters have loaded" — it is
    // "the address bar's own params have been consumed", because the only thing
    // a premature write can destroy is a shared link's params, and the read
    // effect above is what consumes them. The window is one COMMIT wide, not one
    // request: the read effect dispatches, but the write effect in that same
    // commit still closes over the PRE-hydration `filters`, so it would rebuild
    // the query string from the slice's defaults and delete the params of the
    // link the reader just followed. `hydrated` flipping is what ends that
    // window, which is why it is read here — and if the arrival URL carried no
    // params at all, there was never anything to lose and the gate is open on
    // the very first run.
    //
    // Gating on `hydrated` DIRECTLY conflated the two questions and made the
    // feature inert for exactly the audience it exists for. That flag has two
    // producers: this hook's URL read (needs params) and `useHydrateSavedFilters`
    // (needs a signed-in reader AND both queries returning 200). So an anonymous
    // visitor who landed on a bare `/` and then set a filter never got a URL —
    // no error, no log — and neither did a signed-in reader whose saved-filters
    // query failed. Signed-out readers are who you SHARE a link with.
    //
    // MONOTONIC, and that half is what cleans up after a sign-out. Losing the
    // session resets the slice and sets `hydrated` false again
    // (`useHydrateSavedFilters`); re-closing the gate there would strand the ex
    // user's `?time=…&tag=…` in the address bar above a defaults page, and the
    // next reload would re-apply them from that stale URL. Consumed is consumed.
    if (hydrated || arrivalHadParams.current === false) mayWrite.current = true;
    if (!mayWrite.current) return;

    const next = buildSearchFromFilters(filters, window.location.search);
    const current = window.location.search;
    if (next === current) return;

    window.history.replaceState(
      window.history.state,
      '',
      `${window.location.pathname}${next}${window.location.hash}`
    );
  }, [filters, hydrated, isRecentJobsPage]);
}
