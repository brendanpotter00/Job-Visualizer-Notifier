import { useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Container from '@mui/material/Container';
import Link from '@mui/material/Link';
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
import { AddQuotaCounter } from '../../components/my-companies/AddQuotaCounter';
import Divider from '@mui/material/Divider';
import { AddCompanyHowTo } from '../../components/my-companies/AddCompanyHowTo';
import { ResolveUrlForm } from '../../components/my-companies/ResolveUrlForm';
import { AddCompanyOutcome } from '../../components/my-companies/AddCompanyOutcome';
import { MyCompaniesList } from '../../components/my-companies/MyCompaniesList';

/** Ties the "How it works" link to the block it opens (`aria-controls`). */
const HOW_IT_WORKS_ID = 'add-company-how-it-works';

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
  // The SAME cache entry `MyCompaniesList` below subscribes to, so this adds no
  // second request — RTK Query merges the two subscribers. Skipped while signed out
  // for the same reason the list is: the endpoint is authed, and an anonymous
  // visitor would get a guaranteed 401. Declared above the auth ladder's early
  // returns so the hook count stays stable across renders.
  const { data: userCompanies, isSuccess: companiesLoaded } = useGetUserCompaniesQuery(undefined, {
    skip: !isAuthenticated,
  });
  const quota = userCompanies?.quota;
  // Offer the way back to the how-to only to a user who has companies — anyone tracking
  // nothing is already looking at the how-to below, where it IS the empty state.
  //
  // Gated on the SETTLED query, and the direction matters: while the list is loading we
  // do not know which user this is, and a link that appears late is better than one that
  // is drawn and then taken away under the reader's eyes.
  const canReopenHowTo = companiesLoaded && (userCompanies?.companies.length ?? 0) > 0;
  const [showHowTo, setShowHowTo] = useState(false);
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
  const { isLoading: searching, error: searchError } = searchState;

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

  const handleSubmit = (input: string) => {
    // URL-FIRST. A pasted URL is exact and free to resolve, so it takes the same
    // path it always has and never spends a search call. Only an input that
    // cannot be read as a URL becomes a name.
    const classified = classifyCompanyInput(input);

    // With the flag off the box never promised to take a name, so a value that is
    // not a URL still goes to the add endpoint and gets the same guard error it
    // got before this feature existed. Flag-off must behave exactly as before.
    if (classified.kind === 'name' && CUSTOM_COMPANIES_CONFIG.isNameSearchEnabled) {
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
    void addUserCompany({ url: classified.kind === 'url' ? classified.url : input.trim() });
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
    const result = await searchCompanyByName(name);
    // A failed search must SAY so. `AddCompanyOutcome` only ever sees the add
    // mutation's error, so returning quietly here would clear the spinner and
    // leave nothing on screen — a 503 from the flag being off, a Browserbase
    // outage and a dropped connection would all look like the button did
    // nothing at all.
    if (!('data' in result) || !result.data) return;

    const { candidates: found } = result.data;
    const autoAddable = found.filter((c) => c.autoAddable);

    if (found.length === 1 && autoAddable.length === 1) {
      void addUserCompany({ url: autoAddable[0].candidate.sourceUrl });
      return;
    }
    setCandidates(result.data);
  };

  /** Track a candidate the user chose. Clears the list so the outcome is the answer. */
  const handlePickCandidate = (url: string) => {
    if (adding) return;
    setCandidates(null);
    void addUserCompany({ url });
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

          {/* THE WAY BACK TO THE EXPLANATION. The how-to is the empty state, so it
              disappears the moment the user tracks one company — a user who adds a board
              on day one and comes back on day thirty holding a LinkedIn URL would
              otherwise have no way back to it. This is that way back, and deliberately a
              text link rather than an accordion: a shut accordion is a permanent 63px of
              summary row, caret and rule on every visit forever, and this is 29px that
              only a reader who wants it ever spends attention on.

              One component, two triggers: this renders the SAME `AddCompanyHowTo` the
              empty state does, so the two can never drift apart. */}
          {canReopenHowTo ? (
            <>
              <Box sx={{ mt: 1 }}>
                <Link
                  component="button"
                  type="button"
                  variant="body2"
                  color="text.primary"
                  onClick={() => setShowHowTo((open) => !open)}
                  // It changes the page, it does not navigate — so a screen-reader user
                  // is told whether the block is open BEFORE they decide to press it.
                  aria-expanded={showHowTo}
                  aria-controls={HOW_IT_WORKS_ID}
                  data-testid="how-it-works-toggle"
                >
                  How it works
                </Link>
              </Box>
              {/* The container is always present so `aria-controls` always resolves; the
                  content is conditional so nothing invisible is ever in the tab order. */}
              <Box id={HOW_IT_WORKS_ID}>{showHowTo ? <AddCompanyHowTo /> : null}</Box>
            </>
          ) : null}
        </Paper>

        {/* One spinner for the one call. No `!adding` guard on the outcome below it:
            RTK Query clears `data` and `error` the moment a new trigger fires, so the
            outcome renders nothing on its own while a request is in flight — the
            previous URL's answer can never sit under the spinner for the next one. */}
        {adding && <LoadingState minHeight={120} caption="Adding this company…" />}
        {searching && <LoadingState minHeight={120} caption="Looking for their job board…" />}

        {/* A search that FAILED, which is not the same as one that found nothing.
            Without this the spinner would clear and leave an empty page — the
            button would look broken rather than the search looking unavailable. */}
        {searchError && !searching && !adding ? (
          <Alert severity="warning">
            {extractErrorMessage(searchError, 'Could not search for that company.')} You
            can still paste the link to their careers page.
          </Alert>
        ) : null}

        {/* The question, when a name did not resolve to exactly one confident
            board. Hidden while an add is running so it cannot sit beside its own
            answer. */}
        {candidates && !adding ? (
          <CompanyCandidateList
            query={candidates.query}
            candidates={candidates.candidates}
            onPick={handlePickCandidate}
            busy={adding}
          />
        ) : null}

        {/* "We looked and found no board" — a real answer, and NOT the same as
            the 503 that means we could not look. When search turned up the
            company's careers page we hand it over, because that is exactly what
            the paste-a-URL path takes and where one-time discovery starts. */}
        {candidates && candidates.candidates.length === 0 && !adding ? (
          <Paper variant="outlined" sx={{ p: RESPONSIVE.spacing.paperPadding }}>
            <Typography variant="body2">
              No job board found for “{candidates.query}”.{' '}
              {candidates.careersUrl
                ? 'You can try their careers page instead:'
                : 'Try pasting the URL of their careers page.'}
            </Typography>
            {candidates.careersUrl ? (
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                <Typography variant="caption" sx={{ wordBreak: 'break-all' }}>
                  {candidates.careersUrl}
                </Typography>
                <Button
                  size="small"
                  variant="outlined"
                  disabled={adding}
                  onClick={() => handlePickCandidate(candidates.careersUrl as string)}
                >
                  Use this
                </Button>
              </Stack>
            ) : null}
          </Paper>
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
