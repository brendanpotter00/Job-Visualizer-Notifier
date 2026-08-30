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
} from '../../features/userCompanies/userCompaniesApi';
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
  // The SAME cache entry `MyCompaniesList` below subscribes to, so this adds no
  // second request — RTK Query merges the two subscribers. Skipped while signed out
  // for the same reason the list is: the endpoint is authed, and an anonymous
  // visitor would get a guaranteed 401. Declared above the auth ladder's early
  // returns so the hook count stays stable across renders.
  const { data: userCompanies } = useGetUserCompaniesQuery(undefined, {
    skip: !isAuthenticated,
  });
  const quota = userCompanies?.quota;
  // `null` means there is no cap in force (unlimited, or a server that predates the
  // counter). It must NOT disable the form — an absent quota is "we don't know",
  // and locking a user out of the feature on a missing field would be the worst
  // possible reading of it. The server refuses over quota regardless.
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

  const handleSubmit = (url: string) => {
    // `void`: everything rendered below reads from the mutation's own state, and the
    // trigger does not reject (RTK Query resolves it to `{ data }` / `{ error }`), so
    // there is nothing here to await or to catch.
    //
    // The URL the user TYPED, not a normalized one — the endpoint records
    // `submitted_url`, so handing it the original keeps the server-side audit trail
    // matching what was pasted.
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
        {/* THIS COPY IS THE CONSENT, and it had to be rewritten rather than trimmed.
            It used to promise "nothing is tracked until you press Track this company".
            That button is gone, so the sentence became a lie about spending — the one
            kind of copy this page cannot carry, because the submit can start a headless
            browser session and an LLM call on the user's behalf without asking twice.
            Three facts, in the order they matter: the press adds it; an unknown board
            starts paid work immediately; none of it is public. */}
        <Alert severity="info">
          Paste a job board link and press <strong>Add company</strong> — that adds it.
          If it isn&apos;t a board we already read, we start a{' '}
          <strong>one-time setup</strong> that teaches us to read it, and that begins
          immediately. Everything here is <strong>private to you</strong>.
        </Alert>

        <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg }}>
          <ResolveUrlForm
            onSubmit={handleSubmit}
            busy={adding}
            // The submit is what may start a discovery, so it is the control the cap
            // has to close. This is a courtesy, NOT the enforcement: the server
            // refuses over quota with a 422 whatever the button does.
            disabled={exhausted}
          />
        </Paper>

        {/* One spinner for the one call. No `!adding` guard on the outcome below it:
            RTK Query clears `data` and `error` the moment a new trigger fires, so the
            outcome renders nothing on its own while a request is in flight — the
            previous URL's answer can never sit under the spinner for the next one. */}
        {adding && <LoadingState minHeight={120} caption="Adding this company…" />}

        <AddCompanyOutcome
          result={result}
          error={error}
          onTrackAnyway={handleTrackAnyway}
        />

        <Divider />

        {/* The user's saved companies. Signed-in only (this whole block is past
            the auth ladder above), and only ever reachable behind the flag. */}
        <MyCompaniesList />
      </Stack>
    </Container>
  );
}
