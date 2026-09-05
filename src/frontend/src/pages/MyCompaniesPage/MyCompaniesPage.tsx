import { useRef, useState } from 'react';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../config/responsive';
import { BetaBadge } from '../../components/shared/BetaBadge';
import { useAuth } from '../../features/auth/useAuth';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import {
  addsRemaining,
  useAddUserCompanyMutation,
  useGetUserCompaniesQuery,
  useSearchCompanyByNameMutation,
  type SearchCompanyResponse,
} from '../../features/userCompanies/userCompaniesApi';
import { classifyCompanyInput } from '../../features/userCompanies/companyInput';
import { CUSTOM_COMPANIES_CONFIG } from '../../config/customCompanies';
import { extractErrorMessage } from '../../lib/errors';
import { CompanyCandidateList } from '../../components/my-companies/CompanyCandidateList';
import { CareersPageAnswer } from '../../components/my-companies/CareersPageAnswer';
import { DiscoveryStatus } from '../../components/my-companies/DiscoveryStatus';
import { NameSearchProgress } from '../../components/my-companies/NameSearchProgress';
import { AddQuotaCounter } from '../../components/my-companies/AddQuotaCounter';
import Divider from '@mui/material/Divider';
import { ResolveUrlForm } from '../../components/my-companies/ResolveUrlForm';
import { AddCompanyOutcome } from '../../components/my-companies/AddCompanyOutcome';
import { MyCompaniesList } from '../../components/my-companies/MyCompaniesList';

/**
 * "Add Companies" — paste a careers URL, get the company tracked.
 *
 * ONE ACTION, ONE OUTCOME. Pressing **Add company** POSTs `/api/users/companies` and
 * that is the whole flow. There used to be a step in the middle: the page called
 * `POST /api/companies/resolve` first, rendered a preview card ("Found 377 open jobs
 * on Ashby") with a board/how-we-found-it/final-URL grid, and waited for a second
 * press on **Track this company**. The preview answered "is this the right board?"
 * before committing — but it answered it about a board the add endpoint then went and
 * re-resolved from scratch anyway, so the second press decided nothing the first one
 * had not already decided.
 *
 * The add endpoint does the entire job from the raw pasted URL: it re-resolves,
 * probes, applies the burst limit and the monthly cap, runs all three
 * already-published checks, and routes a non-ATS URL into one-time discovery. So the
 * only thing the resolve call ever produced was the preview. `/api/companies/resolve`
 * still exists and is still tested — the frontend just stopped calling it.
 *
 * Reached only when `VITE_CUSTOM_COMPANIES_ENABLED === 'true'` — with the flag
 * off, App.tsx never registers the route.
 */
export function MyCompaniesPage() {
  const { isAuthenticated, isLoading: authLoading, login } = useAuth();
  const [addUserCompany, addState] = useAddUserCompanyMutation();
  const [searchCompanyByName, searchState] = useSearchCompanyByNameMutation();
  // The candidate question, when a typed name did not resolve to exactly one
  // confident board. Held on the page rather than read from `searchState.data`
  // because it must be CLEARED the moment a choice is made — leaving the list up
  // beside the outcome would show a question that has already been answered.
  const [candidates, setCandidates] = useState<SearchCompanyResponse | null>(null);
  // The name a search is currently ABOUT, which is not the same thing as
  // `candidates.query`: this exists from the moment the request goes out, so the
  // narration above the list can name its subject while the answer is still in
  // flight. Null whenever no name search is in play — which is always, with the
  // flag off — and cleared by every path that ends one.
  const [searchedName, setSearchedName] = useState<string | null>(null);
  // The SAME cache entry `MyCompaniesList` below subscribes to, so this adds no
  // second request — RTK Query merges the two subscribers. Skipped while signed out
  // for the same reason the list is: the endpoint is authed, and an anonymous
  // visitor would get a guaranteed 401. Declared above the auth ladder's early
  // returns so the hook count stays stable across renders.
  const { data: userCompanies } = useGetUserCompaniesQuery(undefined, {
    skip: !isAuthenticated,
  });
  /**
   * ONE AUTO-ADD PER PRESS. This ref is the whole enforcement, and it is about money
   * rather than tidiness: every fire POSTs `/api/users/companies`, spends one of the
   * user's 20 monthly adds, and can start a paid discovery run.
   *
   * A ref and not the `adding` flag, because both auto-add paths fire from an async
   * continuation — `adding` is whatever it was at the render that handled the press,
   * which is always `false`, so reading it there would guard nothing. A ref survives
   * every re-render, is per component instance (a StrictMode double-mount gets its
   * own, and cannot share a fired one), and is reset by `handleSubmit` — the single
   * entry point for a new press — so the next search is free to auto-add again.
   *
   * Declared above the auth ladder's early returns so the hook count stays stable.
   */
  const autoAddedRef = useRef(false);
  const quota = userCompanies?.quota;
  // `null` means the payload carried no quota: the caller is an admin (exempt from
  // the cap) or the server predates the counter. Either way it must NOT disable the
  // form — an absent quota is "no cap in force", and locking a user out of the feature
  // on a missing field would be the worst possible reading of it. The server refuses
  // over quota regardless.
  //
  // `0` is the opposite and must stay distinct: a cap that is in force with nothing
  // left, including `limit: 0` (adds turned off), which disables the submit. `=== 0`
  // rather than a falsy check is what keeps `null` out of the exhausted branch.
  const exhausted = addsRemaining(quota) === 0;

  // ── auth ladder (mirrors SavedFiltersPage / AccountPage) ─────────────────
  if (authLoading) {
    return <LoadingState fullPage />;
  }

  if (!isAuthenticated) {
    return (
      <Container maxWidth="sm" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
        <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg, textAlign: 'center' }}>
          {/* `justifyContent: center` because the Paper centres its text and a
              flex heading ignores `textAlign`. */}
          <Typography
            variant="h5"
            gutterBottom
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexWrap: 'wrap',
              gap: 1,
            }}
          >
            Add Companies
            <BetaBadge />
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
            Sign in to add a company from its careers page.
          </Typography>
          <Button variant="contained" onClick={login}>
            Sign In
          </Button>
        </Paper>
      </Container>
    );
  }

  // `isLoading` is the mutation's in-flight flag; RTK Query resets it (and clears
  // `data` / `error`) on each new submit, so the states below are mutually exclusive
  // with no local bookkeeping. The two-phase `busy` flag this page used to hold is
  // gone with the second network call it existed to span.
  const { isLoading: adding, data: result, error } = addState;
  const { isLoading: searching, error: searchError, reset: resetSearch } = searchState;

  // WHICH OF THE TWO ANSWER LAYOUTS BELOW WE ARE IN, and `autoAddable` is the whole
  // rule. One candidate the server was willing to accept makes the list a genuine
  // question worth leading with; none makes every row on screen a board the name gate
  // already threw out, and then the careers page is the answer and the rows are not.
  // Deliberately `.some()` over the whole list rather than the first row — the server
  // orders by search rank, not by confidence.
  const boardsAreTheQuestion =
    candidates !== null && candidates.candidates.some((found) => found.autoAddable);

  // The correction under a GUESSED "we already publish this" notice — the one where the
  // backend matched the company name inside the domain (`matchKind: 'name'`) rather than
  // a board. It re-sends the URL the server settled on with the override, so the board is
  // set up as its own company after all.
  //
  // `DiscoveryStatus` decides whether to render it, and only does so for that guess: an
  // exact board or careers-host match is terminal, because a private duplicate of a board
  // we already publish is strictly worse for the user than the link beside it.
  //
  // It lives HERE because this page owns the add mutation, and its result is what the
  // outcome block renders. A second mutation inside those components would resolve into
  // state nothing on the page reads.
  //
  // The `adding` guard is what the correction's old `isLoading` prop used to buy: firing
  // this unmounts the notice (the mutation's `data` clears, so the outcome block renders
  // the spinner instead of the button), but a double-click can beat that re-render, and
  // each fire spends a monthly slot.
  const handleTrackAnyway = (url: string) => {
    if (adding) return;
    void addUserCompany({ url, trackAnyway: true });
  };

  /**
   * Add a URL the PAGE chose, rather than one the user pressed for — at most once per
   * press. See `autoAddedRef` for why the guard is a ref.
   *
   * The two callers below are the only places the page ever spends an add without a
   * click on the thing being added; every other path (`handlePickCandidate`,
   * `handleTrackAnyway`, `handleSearchTrackAnyway`) is a real press and guards on
   * `adding` instead, which is honest there because those run inside a render.
   */
  const autoAdd = (url: string) => {
    if (autoAddedRef.current) return;
    autoAddedRef.current = true;
    void addUserCompany({ url });
  };

  const handleSubmit = (input: string) => {
    // CLEAR THE PREVIOUS QUESTION BEFORE ASKING ANYTHING ELSE, and this line is
    // load-bearing rather than tidiness. The candidate list renders on
    // `candidates && !adding`, so without this a list left over from an earlier
    // name survives a URL submit and comes BACK once the add finishes — a live
    // "Track this one" for a different company sitting under a success card for
    // the one you just added. That is precisely the wrong-company failure the
    // list exists to prevent, so every submit starts from a blank slate.
    setCandidates(null);
    setSearchedName(null);
    resetSearch();
    // A new press is a new budget. Reset here and nowhere else: this is the only
    // entry point that can legitimately spend another add.
    autoAddedRef.current = false;

    // FLAG OFF MUST BE BYTE-FOR-BYTE THE OLD BEHAVIOUR, which means not even
    // classifying the input. `classifyCompanyInput` normalizes a bare domain to
    // `https://cisco.com`, and doing that with the flag off would change what the
    // server records as `submitted_url` and turn a previously-erroring input into
    // a success — a behaviour change from a feature that is supposed to be dark.
    if (!CUSTOM_COMPANIES_CONFIG.isNameSearchEnabled) {
      void addUserCompany({ url: input.trim() });
      return;
    }

    // URL-FIRST. A pasted URL is exact and free to resolve, so it takes the same
    // path it always has and never spends a search call. Only an input that
    // cannot be read as a URL becomes a name.
    const classified = classifyCompanyInput(input);
    if (classified.kind === 'name') {
      void handleNameSearch(classified.name);
      return;
    }

    // `void`: everything rendered below reads from the mutation's own state, and the
    // trigger does not reject (RTK Query resolves it to `{ data }` / `{ error }`), so
    // there is nothing here to await or to catch.
    //
    // The URL the user TYPED, not a normalized one — the endpoint records
    // `submitted_url`, so handing it the original keeps the server-side audit trail
    // matching what was pasted. The one exception is a bare domain, which
    // `classifyCompanyInput` gives the `https://` the guard requires.
    void addUserCompany({ url: classified.url });
  };

  /**
   * Resolve a typed NAME, then add only if the answer is unambiguous.
   *
   * ONE PRESS, ONE OUTCOME is preserved wherever the evidence allows it: a single
   * candidate the server marked `autoAddable` (its board token names the company
   * AND the board is non-empty) is added straight away, which is the common case.
   *
   * Anything else becomes a question. Measured, an ungated auto-pick tracks
   * another company's live board often enough to matter — Guidehouse's Workday
   * board came back first for "Databricks" with 794 real jobs — and no check we
   * own can tell that apart from a correct answer. A person can, instantly, so
   * the ambiguous cases are handed to one.
   */
  const handleNameSearch = async (name: string) => {
    setCandidates(null);
    // Set BEFORE the await, so the narration's one honest in-flight step is on
    // screen for the whole ~2s the request is actually out.
    setSearchedName(name);
    const result = await searchCompanyByName(name);
    // A failed search must SAY so. `AddCompanyOutcome` only ever sees the add
    // mutation's error, so returning quietly here would clear the spinner and
    // leave nothing on screen — a 503 from the flag being off, a Browserbase
    // outage and a dropped connection would all look like the button did
    // nothing at all.
    if (!('data' in result) || !result.data) return;

    const { candidates: found, careersUrl } = result.data;
    const autoAddable = found.filter((c) => c.autoAddable);

    // A COMPANY WE ALREADY PUBLISH IS NEVER AUTO-ADDED, and this guard is why the
    // check being on the search endpoint is worth anything for the confident case
    // too. Searching a name whose own board we publish resolves exactly one
    // auto-addable candidate, so without this we would spend the add call, spend a
    // monthly slot, and have the SERVER hand back the same "we already publish
    // this" answer we are already holding — the dead end again, one press later,
    // just quieter.
    if (result.data.alreadyPublic) {
      setCandidates(result.data);
      return;
    }

    if (found.length === 1 && autoAddable.length === 1) {
      autoAdd(autoAddable[0].candidate.sourceUrl);
      return;
    }

    /**
     * NO BOARD AND ONE CAREERS PAGE — take it, instead of asking a question that has
     * one answer.
     *
     * What this replaces: a card reading "No job board found for “X” — their careers
     * page is the way in", the URL under it, and a filled **Use this careers page**
     * button. With nothing else on offer that press decided nothing the first one had
     * not already decided, which is the same reasoning that deleted the preview step
     * (this file's header, and `ResolveUrlForm`'s). Owner, 2026-09-03: *"When there is
     * no [board], it should automatically just use that careers website. The idea is
     * to have fewer clicks."*
     *
     * ALL THREE CONDITIONS ARE LOAD-BEARING, and dropping any one takes a real choice
     * away from the user:
     *
     *   - `found.length === 0` — ANY board that came back, even one the name gate
     *     rejected, is an alternative a person might recognise, so it keeps its click.
     *     This is the IBM case: Harvey's live Ashby board sitting beside
     *     `ibm.com/careers`, where only a human can say which one is IBM.
     *   - `careersUrl !== null` — the server picked exactly one and vouched for it
     *     (`services/careers_page_pick.py` collapses the trusted results to a single
     *     URL). Null is a decision, not an absence: no result's host named the company,
     *     so there is nothing here to take.
     *   - not `alreadyPublic` — enforced by the early return above. That answer is "we
     *     already track this", which is never an add.
     *
     * WHAT THIS COSTS, written here because it is a genuine trade and the sentence that
     * used to carry it is gone. Accepting a careers page is exactly what STARTS PAID
     * WORK: a headless browser session and a model call, plus one of the user's 20
     * monthly adds. The disclosure that used to sit under the button — "If this board is
     * new to us, Add company starts a one-time setup right away, about a minute" — was
     * removed at the owner's request on 2026-09-02 (see `ResolveUrlForm` and
     * `src/frontend/CLAUDE.md`). So from here a single press goes from keystroke to paid
     * discovery with NOTHING on screen saying so. That is the owner's call and the spend
     * is still bounded server-side (20 adds per UTC month, a 10/60s burst limit,
     * `CUSTOM_COMPANY_DISCOVERY_ENABLED`) — what is missing is the disclosure, not the
     * cap. Recorded rather than left to be re-derived, the same way the two removals it
     * follows were.
     *
     * A CONSEQUENCE TO KNOW ABOUT: `CareersPageAnswer`'s leading form with a non-null
     * URL and zero unconfirmed boards is now unreachable FROM THIS PAGE. The component
     * still renders it correctly and is left alone — it is one server change (a
     * `careersUrl` beside a confirmed board) away from mattering again.
     */
    if (found.length === 0 && careersUrl !== null) {
      autoAdd(careersUrl);
      return;
    }

    setCandidates(result.data);
  };

  /**
   * The search is over the moment a choice is made — every path that ANSWERS the
   * current question clears it first.
   *
   * Without this the list, the narration and an earlier search's warning all come
   * BACK the instant `adding` goes false, beside the outcome card for the thing
   * that was just added: a live "Track this one" for a different company under a
   * success card for this one.
   */
  const clearSearch = () => {
    setCandidates(null);
    setSearchedName(null);
    resetSearch();
  };

  /** Track a candidate the user chose. Clears the list so the outcome is the answer. */
  const handlePickCandidate = (url: string) => {
    if (adding) return;
    clearSearch();
    void addUserCompany({ url });
  };

  /**
   * "This isn't the same company" — the correction under a GUESSED published match
   * the SEARCH found, before anything was offered.
   *
   * The twin of `handleTrackAnyway`, and it is separate for one reason: that one
   * answers a notice rendered from the add mutation's own `data`, which the new
   * mutation clears by itself. This one answers a notice rendered from page state,
   * so the state has to be cleared here or the notice returns beside the outcome.
   *
   * `DiscoveryStatus` only renders the button for `matchKind === 'name'` — the
   * guess. An exact board or careers-host match is terminal and never calls this.
   */
  const handleSearchTrackAnyway = (url: string) => {
    if (adding) return;
    clearSearch();
    void addUserCompany({ url, trackAnyway: true });
  };

  return (
    <Container maxWidth="md" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      {/* The badge lives INSIDE the `<h1>` so it is part of the heading's
          accessible name ("Add Companies Beta") rather than a decoration a
          screen reader steps over. `flexWrap` keeps it off the title's line
          rather than squeezing the title on a narrow phone. */}
      <Typography
        variant="h4"
        component="h1"
        gutterBottom
        sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1 }}
      >
        Add Companies
        <BetaBadge />
      </Typography>

      {/* The monthly cap, stated once, at the top, as a fact rather than a warning.
          See `AddQuotaCounter` for why there is no alert and no low-balance notice. */}
      <AddQuotaCounter quota={quota} />

      <Stack spacing={3}>
        {/* THE CONSENT MOVED, it did not go. A blue info alert used to sit here saying
            what the press does; it is now one body-size sentence directly under the
            button, inside `ResolveUrlForm`, where the control it describes is. An alert
            above the form is a thing to dismiss with your eyes on the way to the field;
            a line under the button is read by anyone about to press it. */}
        <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg }}>
          <ResolveUrlForm
            onSubmit={handleSubmit}
            busy={adding || searching}
            allowName={CUSTOM_COMPANIES_CONFIG.isNameSearchEnabled}
            // The submit is what may start a discovery, so it is the control the cap
            // has to close. This is a courtesy, NOT the enforcement: the server
            // refuses over quota with a 422 whatever the button does.
            disabled={exhausted}
          />

          {/* NO PERSISTENT "How it works" LINK. One used to sit here for anyone
              already tracking a company, re-opening the same `AddCompanyHowTo` the
              empty state renders. Removed at the owner's request (2026-09-02): "it's
              just unnecessary noise. It should only be there when there's an empty
              state, showing how to do it." The how-to still IS the empty state —
              `MyCompaniesList` renders it for a user tracking nothing — so the
              explanation has not gone, only the way back to it. See
              `src/frontend/CLAUDE.md` for what that costs. */}
        </Paper>

        {/* One spinner for the one call. No `!adding` guard on the outcome below it:
            RTK Query clears `data` and `error` the moment a new trigger fires, so the
            outcome renders nothing on its own while a request is in flight — the
            previous URL's answer can never sit under the spinner for the next one. */}
        {adding && <LoadingState minHeight={120} caption="Adding this company…" />}

        {/* THE SEARCH, NARRATED — and it REPLACES the spinner that used to sit here
            rather than joining it. "Looking for their job board…" over a bare
            CircularProgress said nothing the button press had not already said. These
            steps say what we asked the web, how many results came back, and how many
            of them our own matcher turned into real boards — which is the entire
            argument for typing a name instead of hunting for a URL.

            Hidden while an add runs, and that is what keeps the auto-add path honest:
            a single confident result is added immediately without a list ever
            appearing, and flashing four lines of narration on the way past would be
            motion for something nobody is being asked to read. `NameSearchProgress`
            has the rest — in particular why its only spinner is the request itself. */}
        {!adding ? (
          <NameSearchProgress query={searchedName} searching={searching} result={candidates} />
        ) : null}

        {/* A search that FAILED, which is not the same as one that found nothing.
            Without this the spinner would clear and leave an empty page — the
            button would look broken rather than the search looking unavailable. */}
        {searchError && !searching && !adding ? (
          <Alert severity="warning">
            {extractErrorMessage(searchError, 'Could not search for that company.')} You
            can still paste the link to their careers page.
          </Alert>
        ) : null}

        {/* THE ANSWER, AND THE ORDER IS THE POINT. Two states, and they must not
            look alike:

            A — at least one candidate is `autoAddable`. A real question between
            plausible boards, so the list leads with "Which board is …?" and keeps
            its prominent per-row buttons; the careers page (which the server does
            not normally send in this case) is the footnote beside it.

            B — NOTHING was `autoAddable`. Every board on screen is one the name
            gate already REJECTED, so the careers page goes FIRST and carries the
            weight, and the boards fold away underneath. This is the "meta" bug:
            five other companies' AI boards rendered as five black "Track this one"
            buttons, with `metacareers.com` — the right answer — in caption-grey at
            the bottom. The server was right the whole time; the page was inverted.

            The careers block still renders when there are no candidates at all,
            which is state B with an empty fold: "we looked and found no board" is a
            real answer, and NOT the same as the 503 that means we could not look. A
            null `careersUrl` means something too — no result's host named the
            company, so we offer nothing rather than a guess that would cost a paid
            discovery run and one of their monthly adds.

            AND A THIRD STATE ABOVE BOTH: the search recognised the company as one we
            ALREADY PUBLISH. Then that is the answer, IN PLACE OF the careers-page
            card rather than above it. Typing `databricks` used to render "No job
            board found for “databricks” — their careers page is the way in" over a
            filled "Use this careers page" button, and only the press after it said
            "this looks like Databricks, which we already track". The page invited a
            commitment to something it could already have known was a dead end. The
            boards and the careers page go with it: everything they were for was
            choosing what to add, and there is nothing here to add.

            Same `DiscoveryStatus` the add path uses, so `matchKind` keeps deciding
            what is on offer — `'board'` terminal, `'name'` with its correction. */}
        {candidates && !adding ? (
          candidates.alreadyPublic ? (
            <DiscoveryStatus
              result={candidates.alreadyPublic}
              onTrackAnyway={handleSearchTrackAnyway}
            />
          ) : boardsAreTheQuestion ? (
            <>
              <CompanyCandidateList
                query={candidates.query}
                candidates={candidates.candidates}
                onPick={handlePickCandidate}
                busy={adding}
              />
              <CareersPageAnswer
                query={candidates.query}
                careersUrl={candidates.careersUrl}
                unconfirmedCount={candidates.candidates.length}
                lead={false}
                onUse={handlePickCandidate}
                busy={adding}
              />
            </>
          ) : (
            <>
              <CareersPageAnswer
                query={candidates.query}
                careersUrl={candidates.careersUrl}
                unconfirmedCount={candidates.candidates.length}
                lead
                onUse={handlePickCandidate}
                busy={adding}
              />
              <CompanyCandidateList
                query={candidates.query}
                candidates={candidates.candidates}
                onPick={handlePickCandidate}
                busy={adding}
                demoted
              />
            </>
          )
        ) : null}

        <AddCompanyOutcome result={result} error={error} onTrackAnyway={handleTrackAnyway} />

        <Divider />

        {/* The user's saved companies. Signed-in only (this whole block is past
            the auth ladder above), and only ever reachable behind the flag. */}
        <MyCompaniesList />
      </Stack>
    </Container>
  );
}
