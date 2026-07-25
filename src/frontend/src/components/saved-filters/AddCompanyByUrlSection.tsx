import { useEffect, useRef, useState } from 'react';
import Paper from '@mui/material/Paper';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Box from '@mui/material/Box';
import Alert from '@mui/material/Alert';
import { RESPONSIVE } from '../../config/responsive';
import { useAppDispatch } from '../../app/hooks';
import { useAuth } from '../../features/auth/useAuth';
import {
  useAddCompanyMutation,
  useLazyGetSubmissionQuery,
  userCompaniesApi,
} from '../../features/userCompanies/userCompaniesApi';
import { LoadingState } from '../shared/LoadingIndicator';
import { ErrorState } from '../shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';

/** How often to poll a pending submission while the backend analyzes the site. */
const SUBMISSION_POLL_MS = 2500;
/** Give up after this many polls (~2.5 min) so a stuck submission can't spin forever. */
const MAX_POLLS = 60;

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * "Add a company by URL" section for the Saved Filters page. A signed-in user
 * pastes a careers-page URL; the backend detects the ATS (or builds a custom
 * scraper recipe) and creates the company.
 *
 * A synchronous add (200) appears immediately — the mutation invalidates the
 * `UserCompanies` tag so the dynamic registry refreshes. An async add (202)
 * returns a submission id we poll until it succeeds or fails, showing an
 * "Analyzing site…" progress state; on success we invalidate the registry so the
 * new company shows up and is enable-toggleable.
 *
 * The poll is a user-action-driven async loop (not a fetch-in-effect), matching
 * the project's "user-action mutations stay hand-rolled" rule.
 *
 * Gated on authentication — the page already requires sign-in, but this section
 * self-gates so it is safe to reuse elsewhere.
 */
export function AddCompanyByUrlSection() {
  const { isAuthenticated } = useAuth();
  const dispatch = useAppDispatch();

  const [url, setUrl] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [addCompany, { isLoading: isAdding }] = useAddCompanyMutation();
  const [fetchSubmission] = useLazyGetSubmissionQuery();

  // Guard against setState after unmount during the (long) polling loop.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  if (!isAuthenticated) return null;

  const trimmedUrl = url.trim();
  const busy = isAdding || analyzing;

  // Poll a pending submission until it resolves, the component unmounts, or we
  // hit the poll cap. All state writes happen here in a user-action callback,
  // never synchronously inside an effect.
  const pollSubmission = async (id: string) => {
    for (let i = 0; i < MAX_POLLS; i++) {
      await delay(SUBMISSION_POLL_MS);
      if (!mountedRef.current) return;
      let sub;
      try {
        sub = await fetchSubmission(id).unwrap();
      } catch (err) {
        if (!mountedRef.current) return;
        setAnalyzing(false);
        setErrorMessage(extractErrorMessage(err, 'Failed to check submission status'));
        return;
      }
      if (!mountedRef.current) return;
      if (sub.status === 'succeeded') {
        setAnalyzing(false);
        setUrl('');
        setSuccessMessage(sub.company ? `${sub.company.name} added.` : 'Company added.');
        // The polled query doesn't carry the UserCompanies tag, so refresh the
        // registry explicitly now that the company exists.
        dispatch(userCompaniesApi.util.invalidateTags(['UserCompanies']));
        return;
      }
      if (sub.status === 'failed') {
        setAnalyzing(false);
        setErrorMessage(sub.error ?? 'We could not analyze that site.');
        return;
      }
    }
    if (!mountedRef.current) return;
    setAnalyzing(false);
    setErrorMessage('Timed out while analyzing the site. Please try again.');
  };

  const handleAdd = async () => {
    if (!trimmedUrl || busy) return;
    setSuccessMessage(null);
    setErrorMessage(null);
    try {
      const result = await addCompany({ url: trimmedUrl }).unwrap();
      if (result.status === 'pending') {
        setAnalyzing(true);
        await pollSubmission(result.submissionId);
      } else if (result.status === 'alreadyTracked') {
        setUrl('');
        setSuccessMessage(`${result.company.name} is already tracked.`);
      } else {
        setUrl('');
        setSuccessMessage(`${result.company.name} added.`);
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setAnalyzing(false);
      setErrorMessage(extractErrorMessage(err, 'Failed to add company'));
    }
  };

  return (
    <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg }}>
      <Typography variant="h6" gutterBottom>
        Add a company by URL
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Paste a company&apos;s careers-page URL and we&apos;ll start tracking its job
        postings. We detect the applicant-tracking system automatically.
      </Typography>

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={RESPONSIVE.spacing.filterSpacing}
        alignItems={{ xs: 'stretch', sm: 'flex-start' }}
      >
        <TextField
          fullWidth
          size="small"
          label="Careers page URL"
          placeholder="https://jobs.example.com/careers"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void handleAdd();
            }
          }}
          disabled={busy}
          type="url"
          inputProps={{ 'aria-label': 'Careers page URL' }}
        />
        <Button
          variant="contained"
          onClick={handleAdd}
          disabled={!trimmedUrl || busy}
          sx={{ minWidth: { xs: '100%', sm: 120 } }}
        >
          {isAdding ? 'Adding…' : 'Add'}
        </Button>
      </Stack>

      {analyzing && (
        <Box sx={{ mt: 2 }}>
          <LoadingState minHeight={80} caption="Analyzing site…" />
        </Box>
      )}

      {successMessage && !analyzing && (
        <Alert severity="success" sx={{ mt: 2 }}>
          {successMessage}
        </Alert>
      )}

      {errorMessage && !analyzing && (
        <Box sx={{ mt: 2 }}>
          <ErrorState inline message={errorMessage} />
        </Box>
      )}
    </Paper>
  );
}
