import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  AlertTitle,
  Box,
  Button,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
} from '@mui/material';
import { useAuth } from '../../features/auth/useAuth';
import { extractErrorMessage } from '../../lib/errors';
import { IS_DEV_BUILD, devResetUrl } from '../../config/devReset';

type ResetScope = 'mine' | 'all';

interface DevResetStatus {
  enabled: boolean;
  database_host: string;
}

interface DevResetResult {
  scope: string;
  company_ids: string[];
  deleted: Record<string, number>;
  published_companies_kept: number;
  published_jobs_kept: number;
}

/**
 * LOCAL-DEVELOPMENT-ONLY "clear my custom companies" control.
 *
 * WHAT IT SOLVES. The add-a-company flow can only be tested once per board: the
 * second attempt hits "you already track this" / "we already publish this", and
 * the monthly add quota has spent a slot. This puts the database back to the
 * state where the board was never added, so the real code path runs again.
 *
 * IT RENDERS NOTHING unless BOTH are true:
 *   1. this is a dev build (`IS_DEV_BUILD` is statically false in production, so
 *      this whole component is dropped from the bundle), and
 *   2. the backend answered 200 to `GET /api/users/dev-reset` — which it only
 *      does when `DEV_RESET_ENABLED` is on AND `DATABASE_URL` is a loopback
 *      host. With the flag off the route is not registered at all and 404s.
 *
 * Nothing here decides whether the reset is allowed; it only reflects what the
 * backend already decided. A UI check is a courtesy, never a guard.
 */
export function DevResetPanel() {
  const { getToken } = useAuth();
  const [status, setStatus] = useState<DevResetStatus | null>(null);
  const [scope, setScope] = useState<ResetScope>('mine');
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DevResetResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!IS_DEV_BUILD) return;
    let cancelled = false;

    // Availability is a QUESTION FOR THE BACKEND, and a failure to answer is a
    // "no": an unreachable backend, a 404 (flag off), or a 403 (non-local
    // database) all leave the panel unrendered rather than showing a button
    // that cannot work.
    (async () => {
      try {
        const token = await getToken();
        const response = await fetch(devResetUrl(), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) return;
        const body = (await response.json()) as DevResetStatus;
        if (!cancelled && body?.enabled === true) setStatus(body);
      } catch {
        // Not available. Nothing to report — this control is not part of the
        // page's job, so a missing backend must not surface as a page error.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [getToken]);

  const runReset = useCallback(async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const token = await getToken();
      const response = await fetch(devResetUrl(`?scope=${scope}`), {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        let detail = `Request failed: ${response.status} ${response.statusText}`;
        try {
          const body = await response.json();
          if (body?.detail) detail = String(body.detail);
        } catch {
          // Non-JSON error body; the status line above is what we have.
        }
        setError(detail);
        return;
      }
      setResult((await response.json()) as DevResetResult);
    } catch (err) {
      setError(extractErrorMessage(err, 'Dev reset failed'));
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }, [getToken, scope]);

  if (!IS_DEV_BUILD || status === null) return null;

  const totalDeleted = result
    ? Object.values(result.deleted).reduce((sum, n) => sum + n, 0)
    : 0;

  return (
    <Paper
      variant="outlined"
      sx={{ mb: 4, p: 2, borderColor: 'error.main', borderWidth: 2 }}
      data-testid="dev-reset-panel"
    >
      <Typography variant="h5" gutterBottom color="error">
        Danger zone — local development only
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Deletes user-added (custom) companies and everything they own: ownership
        rows, the add-attempt audit (which also resets the 20/month add quota),
        scrape recipes, discovery progress, harvests, runs, and every scraped job
        under <code>custom:&lt;id&gt;</code>. Published companies and their jobs are
        never touched. This cannot be undone. Database:{' '}
        <strong>{status.database_host}</strong>.
      </Typography>

      <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" useFlexGap>
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel id="dev-reset-scope-label">Scope</InputLabel>
          <Select
            labelId="dev-reset-scope-label"
            value={scope}
            label="Scope"
            disabled={busy || confirming}
            onChange={(e) => setScope(e.target.value as ResetScope)}
          >
            <MenuItem value="mine">Only my companies</MenuItem>
            <MenuItem value="all">Every user&apos;s companies</MenuItem>
          </Select>
        </FormControl>

        {!confirming && (
          <Button
            variant="outlined"
            color="error"
            disabled={busy}
            onClick={() => {
              setConfirming(true);
              setResult(null);
              setError(null);
            }}
          >
            Clear custom companies
          </Button>
        )}

        {confirming && (
          <>
            <Typography variant="body2" color="error">
              {scope === 'all'
                ? 'Permanently delete EVERY user’s custom companies and their jobs?'
                : 'Permanently delete your custom companies and their jobs?'}
            </Typography>
            <Button
              variant="contained"
              color="error"
              disabled={busy}
              onClick={runReset}
              startIcon={busy ? <CircularProgress size={16} color="inherit" /> : null}
            >
              {busy ? 'Clearing…' : 'Yes, delete'}
            </Button>
            <Button variant="text" disabled={busy} onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </>
        )}
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}

      {result && (
        <Alert severity="success" sx={{ mt: 2 }}>
          <AlertTitle>
            Deleted {totalDeleted} row{totalDeleted === 1 ? '' : 's'} across{' '}
            {result.company_ids.length} custom compan
            {result.company_ids.length === 1 ? 'y' : 'ies'}
          </AlertTitle>
          <Box component="ul" sx={{ m: 0, pl: 3 }}>
            {Object.entries(result.deleted)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([table, count]) => (
                <li key={table}>
                  {table}: {count}
                </li>
              ))}
          </Box>
          <Typography variant="body2" sx={{ mt: 1 }}>
            Left untouched: {result.published_companies_kept} published companies,{' '}
            {result.published_jobs_kept} published job rows.
          </Typography>
        </Alert>
      )}
    </Paper>
  );
}
