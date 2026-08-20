import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Collapse from '@mui/material/Collapse';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { ROUTES } from '../../config/routes';
import type {
  DiscoveryStep,
  UserCompany,
} from '../../features/userCompanies/userCompaniesApi';
import {
  describeDiscoveryOutcome,
  describeDiscoveryStep,
  failedDiscoveryStep,
  resolveDiscoveryOutcome,
} from './companyHealth';
import { DiscoveryJobPreview } from './DiscoveryJobPreview';

/** Status glyph per step. Text, not icons, so the state survives a screenshot. */
const STEP_MARK: Record<DiscoveryStep['status'], string> = {
  pending: '○',
  active: '',
  done: '✓',
  failed: '✕',
};

const STEP_COLOR: Record<DiscoveryStep['status'], string> = {
  pending: 'text.disabled',
  active: 'text.primary',
  done: 'success.main',
  failed: 'error.main',
};

/**
 * A read-only, iframe-embeddable view of the capture session, appended so the hosted
 * page renders without its own chrome. Only ever applied to an https URL the backend
 * already vetted.
 */
function liveViewSrc(url: string): string {
  return url.includes('navbar=') ? url : `${url}${url.includes('?') ? '&' : '?'}navbar=false`;
}

function StepRow({ step }: { step: DiscoveryStep }) {
  const mark = STEP_MARK[step.status] ?? '○';
  return (
    <Stack direction="row" spacing={1} alignItems="flex-start" data-testid={`discovery-step-${step.key}`}>
      <Box sx={{ width: 20, flexShrink: 0, textAlign: 'center', lineHeight: '1.5rem' }}>
        {step.status === 'active' ? (
          <CircularProgress size={12} aria-label="in progress" />
        ) : (
          <Typography component="span" color={STEP_COLOR[step.status] ?? 'text.disabled'}>
            {mark}
          </Typography>
        )}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography
          variant="body2"
          color={step.status === 'pending' ? 'text.disabled' : 'text.primary'}
          sx={{ fontWeight: step.status === 'active' ? 600 : 400 }}
        >
          {describeDiscoveryStep(step)}
        </Typography>
        {/* The SPECIFIC result is the point of the whole checklist — "found 3 candidate
            feeds" is what tells a user we are looking at their board; a bare tick is a
            spinner with extra steps. */}
        {step.result ? (
          <Typography
            variant="caption"
            color={step.status === 'failed' ? 'error.main' : 'text.secondary'}
            sx={{ display: 'block', overflowWrap: 'anywhere' }}
            data-testid={`discovery-result-${step.key}`}
          >
            {step.result}
          </Typography>
        ) : null}
      </Box>
    </Stack>
  );
}

/**
 * What to do when we could not read a board. Deliberately NOT a retry button.
 *
 * Discovery is deterministic: the same URL runs the same capture and reaches the same
 * refusal, so "try again" spends a browser session and an LLM call to reproduce the
 * answer the user already has. Every action here changes an input instead.
 */
function NextActions({ boardUrl }: { boardUrl: string }) {
  return (
    <Box sx={{ mt: 1.5 }} data-testid="discovery-next-actions">
      <Typography variant="subtitle2" gutterBottom>
        What you can do
      </Typography>
      <Stack component="ul" spacing={0.75} sx={{ m: 0, pl: 2.5 }}>
        <Typography component="li" variant="body2">
          <strong>Paste the direct board URL.</strong> Many careers pages embed a
          Greenhouse, Ashby or Lever board — open a job from{' '}
          <Link href={boardUrl} target="_blank" rel="noopener noreferrer">
            this careers page
          </Link>{' '}
          and paste the address you land on instead.
        </Typography>
        <Typography component="li" variant="body2">
          <strong>Tell us about this board.</strong>{' '}
          <Link component={RouterLink} to={ROUTES.VOTE_FEATURES}>
            Send it through as feedback
          </Link>{' '}
          and we&apos;ll look at supporting it.
        </Typography>
        <Typography component="li" variant="body2">
          <strong>Remove it.</strong> Nothing is being scraped for this board, so it is
          only taking up a row — use <strong>Remove</strong> above to clear it.
        </Typography>
      </Stack>
    </Box>
  );
}

interface DiscoveryChecklistProps {
  company: UserCompany;
}

/**
 * The 4-step discovery checklist that replaced the "Setting up…" spinner.
 *
 * Because the capture engine's steps are deterministic and known before the run
 * starts, they can be named up front and ticked off with what each one actually found
 * — ending in either a job preview ("we can read this board") or a refusal that names
 * the step that stopped, framed as "we couldn't read {Company}'s board" with real next
 * actions.
 *
 * Presentational and flag-free: the caller decides whether the feature is on. It reads
 * only `company`, whose `discovery` blob arrives on the list poll the page already runs
 * — there is no second polling channel and no fetching here.
 *
 * The live view is OPTIONAL and degrades silently (DECISION D4): only a Browserbase
 * capture has one and our default is our own Chromium, so on almost every run there is
 * no iframe and no toggle at all. It stays behind a collapsed "Watch live" button on
 * every breakpoint rather than only on mobile — the checklist is the thing worth
 * reading, a size-dependent default would need a second source of truth for the
 * collapse state, and the iframe is `pointer-events: none` so it is a picture either
 * way.
 */
export function DiscoveryChecklist({ company }: DiscoveryChecklistProps) {
  const [liveOpen, setLiveOpen] = useState(false);
  const discovery = company.discovery;
  if (!discovery) {
    return null;
  }

  const outcome = resolveDiscoveryOutcome(company);
  const headline = describeDiscoveryOutcome(company);
  const failed = failedDiscoveryStep(discovery);
  const liveViewUrl = outcome === 'running' ? discovery.liveViewUrl : null;

  return (
    <Paper
      variant="outlined"
      sx={{ mt: 1.5, p: 1.5, bgcolor: 'action.hover' }}
      data-testid="discovery-checklist"
      data-outcome={outcome}
    >
      <Typography variant="subtitle2" data-testid="discovery-headline">
        {headline.title}
      </Typography>
      {/* The ✓/✕ chain: "Found the feed ✓ · Couldn't confirm the results match ✕".
          Rendered even on success — it is the one-line version of the list below. */}
      {headline.summary ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: 'block', mb: 1 }}
          data-testid="discovery-summary"
        >
          {headline.summary}
        </Typography>
      ) : null}

      <Stack spacing={0.75} sx={{ mt: 1 }}>
        {discovery.steps.map((step) => (
          <StepRow key={step.key} step={step} />
        ))}
      </Stack>

      {outcome === 'tracking' ? <DiscoveryJobPreview jobs={discovery.jobPreview} /> : null}

      {outcome === 'refused' ? (
        <>
          {/* A timeout fails no step, so there is nothing to name — say that plainly
              rather than leaving the user staring at four unresolved rungs. */}
          {failed === null ? (
            <Typography
              variant="body2"
              color="error.main"
              sx={{ mt: 1.5 }}
              data-testid="discovery-stalled"
            >
              This setup stopped before it could finish.
            </Typography>
          ) : null}
          <NextActions boardUrl={company.boardToken} />
        </>
      ) : null}

      {liveViewUrl ? (
        <Box sx={{ mt: 1.5 }}>
          <Button
            size="small"
            onClick={() => setLiveOpen((open) => !open)}
            aria-expanded={liveOpen}
            data-testid="discovery-live-view-toggle"
          >
            {liveOpen ? 'Hide live view' : 'Watch live'}
          </Button>
          <Collapse in={liveOpen}>
            <Box
              // `pointer-events: none` — read-only by construction. This is someone
              // else's hosted browser session; it is here to be watched, never driven.
              sx={{
                mt: 1,
                pointerEvents: 'none',
                position: 'relative',
                width: '100%',
                aspectRatio: '16 / 10',
                overflow: 'hidden',
                borderRadius: 1,
              }}
            >
              <Box
                component="iframe"
                src={liveViewSrc(liveViewUrl)}
                title="Live view of the setup session"
                sandbox="allow-scripts allow-same-origin"
                data-testid="discovery-live-view"
                sx={{ width: '100%', height: '100%', border: 0 }}
              />
            </Box>
          </Collapse>
        </Box>
      ) : null}
    </Paper>
  );
}
