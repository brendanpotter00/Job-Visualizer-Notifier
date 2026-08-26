import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../config/responsive';
import { useAuth } from '../../features/auth/useAuth';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import {
  useAddUserCompanyMutation,
  useResolveCareersUrlMutation,
} from '../../features/userCompanies/userCompaniesApi';
import Divider from '@mui/material/Divider';
import { ResolveUrlForm } from '../../components/my-companies/ResolveUrlForm';
import { ResolveResultDisplay } from '../../components/my-companies/ResolveResultDisplay';
import { ResolveErrorDisplay } from '../../components/my-companies/ResolveErrorDisplay';
import { DiscoveryStatus } from '../../components/my-companies/DiscoveryStatus';
import { MyCompaniesList } from '../../components/my-companies/MyCompaniesList';
import { describeResolveError } from '../../features/userCompanies/resolveErrors';
import { useState } from 'react';

/**
 * "Add Companies" — paste a careers URL, get the company tracked.
 *
 * ONE user action covers both outcomes. The submit runs the ATS resolver; if a supported
 * board is behind the URL the user still gets the preview and an explicit "Track this
 * company" confirm (a readable board is cheap and reversible, and the job count is worth
 * seeing before committing). If the resolver finds NO supported board, the same action
 * immediately hands the URL to one-time discovery instead of parking the user in front of
 * a second button — that second click was the whole defect this page's copy now has to
 * pay for by naming the spend up front.
 *
 * Reached only when `VITE_CUSTOM_COMPANIES_ENABLED === 'true'` — with the flag
 * off, App.tsx never registers the route.
 */
export function MyCompaniesPage() {
  const { isAuthenticated, isLoading: authLoading, login } = useAuth();
  const [resolveCareersUrl, resolveState] = useResolveCareersUrlMutation();
  const [addUserCompany, addState] = useAddUserCompanyMutation();
  // One busy flag for the WHOLE action, flipped synchronously around the pair of calls
  // rather than derived from the two mutations' `isLoading`. Between the resolve
  // rejecting and the discovery POST being dispatched both are idle, so a derived flag
  // would re-enable the form and flash the raw resolver error for a frame in the middle
  // of an action that is still running. It is also what keeps a PREVIOUS URL's discovery
  // outcome off the screen while the next one runs, so no explicit mutation reset is
  // needed. Declared here — ABOVE the auth ladder's early
  // returns — so the hook count stays stable across renders (a hook after a conditional
  // return breaks the Rules of Hooks).
  const [busy, setBusy] = useState(false);

  // ── auth ladder (mirrors SavedFiltersPage / AccountPage) ─────────────────
  if (authLoading) {
    return <LoadingState fullPage />;
  }

  if (!isAuthenticated) {
    return (
      <Container maxWidth="sm" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
        <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg, textAlign: 'center' }}>
          <Typography variant="h5" gutterBottom>
            Add Companies
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
            Sign in to check whether a company&apos;s careers page can be tracked.
          </Typography>
          <Button variant="contained" onClick={login}>
            Sign In
          </Button>
        </Paper>
      </Container>
    );
  }

  // `isLoading` is the mutation's in-flight flag; RTK Query resets it (and
  // clears `data` / `error`) on each new submit, so the states below are
  // mutually exclusive without any local bookkeeping.
  const { isLoading: resolving, data: result, error } = resolveState;
  const noAtsDetected =
    error !== undefined && describeResolveError(error).reasonCode === 'no_ats_detected';

  const runCheck = async (url: string) => {
    setBusy(true);
    try {
      const outcome = await resolveCareersUrl({ url });
      // The auto-start, and the narrowest possible trigger for it. ONLY
      // `no_ats_detected` — "we read the page and there is no board we support" — is a
      // job for discovery. A malformed URL, an SSRF refusal, a 429, a 503, or a resolver
      // timeout must stay a plain error: spending a Claude call and a headless Chromium
      // session on a typo is exactly the failure this check prevents.
      if (
        'error' in outcome &&
        describeResolveError(outcome.error).reasonCode === 'no_ats_detected'
      ) {
        // The URL the user submitted, not the resolver's `finalUrl` — the add endpoint
        // re-resolves from scratch and records `submitted_url`, so handing it the
        // original keeps the server-side audit trail matching what was typed.
        await addUserCompany({ url });
      }
    } finally {
      setBusy(false);
    }
  };

  // The escape hatch under "we already publish this board". It re-sends the URL the
  // server settled on with the override, so the private copy is created after all.
  //
  // It lives HERE rather than in `DiscoveryStatus` for the same reason the auto-start
  // does: this page owns the add mutation, and its result is what `DiscoveryStatus`
  // renders. A second mutation inside that component would resolve into state nothing
  // on the page reads. It deliberately does NOT touch `busy` — that flag spans the
  // resolve→discovery handoff, and raising it here would hide the notice the user just
  // acted on behind a spinner; `addState.isLoading` disables the button instead.
  const handleTrackAnyway = (url: string) => {
    void addUserCompany({ url, trackAnyway: true });
  };

  const handleSubmit = (url: string) => {
    // `void`: everything rendered below reads from the two mutations' own state, and
    // neither trigger rejects (RTK Query resolves them to `{ data }` / `{ error }`), so
    // there is nothing here to await or to catch.
    void runCheck(url);
  };

  return (
    <Container maxWidth="md" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Add Companies
      </Typography>

      <Stack spacing={3}>
        {/* This copy is the consent. The submit below can spend real work on the user's
            behalf without asking a second time, so the two outcomes — preview-then-choose
            vs. setup-starts-now — have to be stated before they paste anything. Trimmed,
            not softened: "nothing is tracked until you press" and "that begins straight
            away" are the two halves that make it consent, and the only words cut are the
            ones the setup notice below repeats verbatim once a setup actually starts. */}
        <Alert severity="info">
          Paste a careers URL. If it&apos;s a job board we already read, you&apos;ll see what
          we found and nothing is tracked until you press{' '}
          <strong>Track this company</strong>. If it isn&apos;t, we start a{' '}
          <strong>one-time setup</strong> that teaches us to read it — that begins straight
          away. Everything here is <strong>private to you</strong>.
        </Alert>

        <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg }}>
          <ResolveUrlForm
            onSubmit={handleSubmit}
            status={resolving ? 'checking' : busy ? 'setting-up' : 'idle'}
          />
        </Paper>

        {/* One spinner for both halves of the action — `busy` spans the handoff, so the
            caption changes without the UI ever going dead between the two calls. */}
        {busy && (
          <LoadingState
            minHeight={120}
            caption={resolving ? 'Checking that URL…' : 'Setting this board up…'}
          />
        )}

        {/* A resolver failure we are NOT acting on: show it as the error it is. The
            `no_ats_detected` case is deliberately excluded — discovery is already running
            for it, and a red "we couldn't find a job board" above a working setup would
            report a failure that isn't one. */}
        {!busy && error !== undefined && !noAtsDetected && <ResolveErrorDisplay error={error} />}

        {!busy && noAtsDetected && (
          <DiscoveryStatus
            result={addState.data}
            error={addState.error}
            onTrackAnyway={handleTrackAnyway}
            isTracking={addState.isLoading}
          />
        )}

        {!busy && error === undefined && result !== undefined && (
          <ResolveResultDisplay result={result} />
        )}

        <Divider />

        {/* The user's saved companies. Signed-in only (this whole block is past
            the auth ladder above), and only ever reachable behind the flag. */}
        <MyCompaniesList />
      </Stack>
    </Container>
  );
}
