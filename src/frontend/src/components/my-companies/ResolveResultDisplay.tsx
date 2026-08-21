import { useState } from 'react';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import Divider from '@mui/material/Divider';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import type { ResolveUrlResponse } from '../../features/userCompanies/userCompaniesApi';
import { AddCompanyCTA } from './AddCompanyCTA';

interface ResolveResultDisplayProps {
  result: ResolveUrlResponse;
}

/** Display names for the ATS providers the resolver can return. */
const ATS_LABELS: Record<string, string> = {
  greenhouse: 'Greenhouse',
  ashby: 'Ashby',
  lever: 'Lever',
  gem: 'Gem',
  workday: 'Workday',
  eightfold: 'Eightfold',
};

/**
 * `ats` is a bare string on the wire, so an unknown provider is possible if the
 * server ships one before the frontend does. Show the raw value rather than
 * blanking the most important word in the headline.
 */
function atsLabel(ats: string): string {
  return ATS_LABELS[ats] ?? ats;
}

/** Plain-English gloss for `via`, which is otherwise a bare jargon token. */
const VIA_EXPLANATIONS: Record<string, string> = {
  direct: 'The URL you pasted was the job board itself.',
  redirect: 'The URL you pasted redirected to the job board.',
  embedded: 'The job board was embedded in the page you pasted.',
};

function viaExplanation(via: string): string {
  return VIA_EXPLANATIONS[via] ?? `Found via "${via}".`;
}

/** One label/value row in the details grid. */
function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={{ xs: 0.25, sm: 2 }}>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ minWidth: 132, flexShrink: 0, fontWeight: 500 }}
      >
        {label}
      </Typography>
      <Box sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>{children}</Box>
    </Stack>
  );
}

/**
 * Renders a successful (HTTP 200) resolve.
 *
 * Two genuinely different outcomes share this status code:
 *  - `probe.ok === true`  — we found the board AND read its open roles.
 *  - `probe.ok === false` — we found the board but the call to it failed. The
 *    job count is meaningless here, so it is replaced by the probe error rather
 *    than shown as a confident "0 open jobs".
 */
export function ResolveResultDisplay({ result }: ResolveResultDisplayProps) {
  const [hopsOpen, setHopsOpen] = useState(false);
  const { candidate, probe, via, hops, finalUrl } = result;

  return (
    <Paper variant="outlined" sx={{ p: 3 }} data-testid="resolve-result">
      {probe.ok ? (
        <Box sx={{ mb: 2 }}>
          <Typography variant="h5" component="p" data-testid="resolve-headline">
            Found {probe.jobCount.toLocaleString()} open{' '}
            {probe.jobCount === 1 ? 'job' : 'jobs'} on {atsLabel(candidate.ats)}
          </Typography>
          {/* No "This board can be tracked." under that headline: finding 663 open jobs
              IS the statement that it can be tracked, and the button below says the rest. */}
          {/* Persist the resolved board to the caller's account. Lives inside
              the `probe.ok` branch because only a readable board can be tracked. */}
          <AddCompanyCTA finalUrl={finalUrl} />
        </Box>
      ) : (
        <Alert severity="warning" sx={{ mb: 2 }} data-testid="resolve-probe-failed">
          <AlertTitle>
            Found a {atsLabel(candidate.ats)} board, but couldn&apos;t read it
          </AlertTitle>
          <Typography variant="body2">
            We identified the job board behind that URL, but the request for its open roles
            failed, so we don&apos;t know how many jobs it has.
          </Typography>
          {probe.error && (
            <Typography
              variant="caption"
              sx={{ display: 'block', mt: 1, fontFamily: 'monospace' }}
              data-testid="probe-error"
            >
              {probe.error}
            </Typography>
          )}
        </Alert>
      )}

      <Divider sx={{ mb: 2 }} />

      <Stack spacing={1.5}>
        <DetailRow label="Job board">
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Chip size="small" label={atsLabel(candidate.ats)} />
            <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
              {candidate.boardToken}
            </Typography>
          </Stack>
        </DetailRow>

        <DetailRow label="How we found it">
          <Typography variant="body2">{viaExplanation(via)}</Typography>
        </DetailRow>

        <DetailRow label="Final URL">
          <Link href={finalUrl} target="_blank" rel="noopener noreferrer" variant="body2">
            {finalUrl}
          </Link>
        </DetailRow>

        {/* A "Board settings" row used to print the raw `providerConfig` here —
            `baseUrl: https://intel.wd1.myworkdayjobs.com`, `tenantSlug: intel`. That is
            the machine's copy of what "Final URL" above already says in a form a person
            can click, so it was three lines of config on a card whose job is to answer
            one question: is this the right board? */}
      </Stack>

      {hops.length > 0 && (
        <Box sx={{ mt: 2 }}>
          <Button
            size="small"
            onClick={() => setHopsOpen((open) => !open)}
            aria-expanded={hopsOpen}
          >
            {hopsOpen ? 'Hide' : 'Show'} redirect chain ({hops.length})
          </Button>
          <Collapse in={hopsOpen}>
            <Stack
              component="ol"
              spacing={0.5}
              sx={{ mt: 1, pl: 3, mb: 0 }}
              data-testid="resolve-hops"
            >
              {hops.map((hop, index) => (
                <Typography
                  component="li"
                  // Hops can legitimately repeat within one chain, so the URL
                  // alone is not a stable key.
                  key={`${index}-${hop}`}
                  variant="body2"
                  sx={{ overflowWrap: 'anywhere' }}
                >
                  {hop}
                </Typography>
              ))}
            </Stack>
          </Collapse>
        </Box>
      )}
    </Paper>
  );
}
