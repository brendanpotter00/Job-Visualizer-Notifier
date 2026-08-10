import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Container from '@mui/material/Container';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { RESPONSIVE } from '../../config/responsive';
import { useAuth } from '../../features/auth/useAuth';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { useResolveCareersUrlMutation } from '../../features/userCompanies/userCompaniesApi';
import Divider from '@mui/material/Divider';
import { ResolveUrlForm } from '../../components/my-companies/ResolveUrlForm';
import { ResolveResultDisplay } from '../../components/my-companies/ResolveResultDisplay';
import { ResolveErrorDisplay } from '../../components/my-companies/ResolveErrorDisplay';
import { DiscoveryCTA } from '../../components/my-companies/DiscoveryCTA';
import { MyCompaniesList } from '../../components/my-companies/MyCompaniesList';
import { describeResolveError } from '../../features/userCompanies/resolveErrors';
import { useState } from 'react';

/**
 * "My Companies" — currently a resolve-only preview.
 *
 * This page checks whether a pasted careers URL hides a job board we can read.
 * It deliberately persists NOTHING: there is no saved list, no company record,
 * no scraping scheduled. Saving arrives with the backend endpoints that store
 * user-owned companies. The copy below has to keep saying so, because a page
 * titled "My Companies" that reports "Found 663 open jobs" reads like it just
 * added something.
 *
 * Reached only when `VITE_CUSTOM_COMPANIES_ENABLED === 'true'` — with the flag
 * off, App.tsx never registers the route.
 */
export function MyCompaniesPage() {
  const { isAuthenticated, isLoading: authLoading, login } = useAuth();
  const [resolveCareersUrl, resolveState] = useResolveCareersUrlMutation();

  // ── auth ladder (mirrors SavedFiltersPage / AccountPage) ─────────────────
  if (authLoading) {
    return <LoadingState fullPage />;
  }

  if (!isAuthenticated) {
    return (
      <Container maxWidth="sm" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
        <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg, textAlign: 'center' }}>
          <Typography variant="h5" gutterBottom>
            My Companies
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
  // clears `data` / `error`) on each new submit, so the three states below are
  // mutually exclusive without any local bookkeeping.
  const { isLoading: resolving, data: result, error } = resolveState;
  // Keep the last-submitted URL so a "no ATS found" result can offer one-time
  // discovery against the same address.
  const [lastUrl, setLastUrl] = useState('');
  const noAtsDetected =
    error !== undefined && describeResolveError(error).reasonCode === 'no_ats_detected';

  const handleSubmit = (url: string) => {
    setLastUrl(url);
    // Fire-and-forget: the rendered state comes from `resolveState`, and an
    // unhandled rejection here would be noise — the error is already surfaced.
    void resolveCareersUrl({ url });
  };

  return (
    <Container maxWidth="md" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      <Typography variant="h4" component="h1" gutterBottom>
        My Companies
      </Typography>

      <Stack spacing={3}>
        <Alert severity="info">
          Paste a careers URL to <strong>check</strong> whether we can read the job board behind
          it. If we can, add it with <strong>Track this company</strong> and we&apos;ll start
          building its hiring history — <strong>private to you</strong>. Nothing is added to your
          account until you choose to track it.
        </Alert>

        <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg }}>
          <ResolveUrlForm onSubmit={handleSubmit} resolving={resolving} />
        </Paper>

        {resolving && <LoadingState minHeight={120} caption="Checking that URL…" />}

        {!resolving && error !== undefined && (
          <>
            <ResolveErrorDisplay error={error} />
            {noAtsDetected && lastUrl && <DiscoveryCTA url={lastUrl} />}
          </>
        )}

        {!resolving && error === undefined && result !== undefined && (
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
