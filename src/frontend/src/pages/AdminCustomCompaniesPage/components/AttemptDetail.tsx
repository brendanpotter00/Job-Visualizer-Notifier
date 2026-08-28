import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { describeDiscoveryStep } from '../../../components/my-companies/companyHealth';
import type { AdminCustomCompanyAttemptRow } from '../../../features/admin/adminApi';
import type { DiscoveryStep } from '../../../features/userCompanies/userCompaniesApi';
import { formatDuration, formatTimestamp } from '../format';

/**
 * Everything known about ONE add attempt, rendered once and framed twice — the
 * desktop table drops it inside a `<Collapse>`, the mobile card list drops it
 * inside a `<Dialog>`. Two frames, one implementation, so the phone can never
 * quietly show less than the desktop does.
 *
 * Two panels side by side on wide screens, stacked on narrow ones:
 *
 *  - The DISCOVERY CHECKLIST, straight from
 *    `provider_config->'discovery'->'steps'` — which only survives as long as
 *    the `companies` row does. Most attempts in this table point at a board the
 *    user has since deleted (deleting hard-deletes the row), so the null case
 *    is the COMMON case, not the edge one, and it falls back to `errorDetail`.
 *  - The ATTEMPT RECORD, which is what the audit log still remembers after the
 *    board itself is gone.
 */

/** Glyph per rendered status. Text, not icons, so the state survives a screenshot. */
const STEP_MARK: Record<DiscoveryStep['status'], string> = {
  pending: '○',
  active: '◔',
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
 * How a rung DRAWS, which is not always the status the blob carries.
 *
 * A discovery that timed out writes no terminal checklist, so its last live
 * snapshot survives with a step still marked `active`. On an attempt that has
 * already ended, that rung is "the one we never got past" — a grey ○ — not a
 * step still in flight. Only a genuinely in-flight attempt (`pending`) keeps
 * the active mark. Same rule as `DiscoveryChecklist.renderedStatus`.
 */
function renderedStatus(
  step: DiscoveryStep,
  isInFlight: boolean
): DiscoveryStep['status'] {
  return step.status === 'active' && !isInFlight ? 'pending' : step.status;
}

function StepRow({ step, isInFlight }: { step: DiscoveryStep; isInFlight: boolean }) {
  const status = renderedStatus(step, isInFlight);
  return (
    <Stack direction="row" spacing={1} alignItems="flex-start">
      <Box sx={{ width: 16, flexShrink: 0, textAlign: 'center' }}>
        <Typography component="span" variant="body2" color={STEP_COLOR[status]}>
          {STEP_MARK[status]}
        </Typography>
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography
          variant="body2"
          color={status === 'pending' ? 'text.disabled' : 'text.primary'}
          sx={{ fontWeight: status === 'failed' ? 600 : 400 }}
        >
          {/* Reused from the user-facing checklist (which reads DISCOVERY_STEP_LABELS)
              so the two pages never drift apart on what a rung is called. */}
          {describeDiscoveryStep(step)}
        </Typography>
        {step.result ? (
          <Typography
            variant="caption"
            color={status === 'failed' ? 'error.main' : 'text.secondary'}
            sx={{ display: 'block', overflowWrap: 'anywhere' }}
          >
            {step.result}
          </Typography>
        ) : null}
      </Box>
    </Stack>
  );
}

/** One `label  value` line of the attempt record. */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Typography variant="body2" sx={{ mb: 0.5, overflowWrap: 'anywhere' }}>
      <Typography component="span" variant="body2" color="text.secondary">
        {label}
      </Typography>{' '}
      {children}
    </Typography>
  );
}

export function AttemptDetail({ row }: { row: AdminCustomCompanyAttemptRow }) {
  const isInFlight = row.outcome === 'pending';
  const steps = row.discoverySteps;

  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: 'minmax(0, 1fr)', md: 'minmax(0, 1.05fr) minmax(0, 1fr)' },
        gap: { xs: 2, md: 4 },
      }}
    >
      <Box>
        <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
          Discovery checklist
        </Typography>
        {steps && steps.length > 0 ? (
          <Stack spacing={0.5}>
            {steps.map((step) => (
              <StepRow key={step.key} step={step} isInFlight={isInFlight} />
            ))}
          </Stack>
        ) : (
          <>
            {/* No checklist survives, so the split `error_detail` IS the
                account of what happened. The engine's step vocabulary here
                ("verifying we can read it") is deliberately not translated into
                the checklist's ("Building web scraper") — the map between them
                lives in the capture module and importing it would drag
                playwright into the admin bundle. */}
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              No checklist stored — the company row was deleted.
            </Typography>
            {row.failedStep ? (
              <Typography variant="body2" color="error.main" sx={{ fontWeight: 600 }}>
                {row.failedStep} ✕
              </Typography>
            ) : null}
            {row.failureReason ? (
              <Typography variant="body2" color="error.main" sx={{ overflowWrap: 'anywhere' }}>
                {row.failureReason}
              </Typography>
            ) : null}
            {!row.errorDetail ? (
              <Typography variant="body2" color="text.disabled">
                No failure recorded for this attempt.
              </Typography>
            ) : null}
          </>
        )}
      </Box>

      <Box>
        <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
          Attempt record
        </Typography>
        <Field label="Submitted URL">
          <Box component="span" sx={{ fontFamily: 'monospace', fontSize: '0.8125rem' }}>
            {row.submittedUrl}
          </Box>
        </Field>
        <Field label="Normalized URL">
          {row.normalizedUrl === null ? (
            <Typography component="span" variant="body2" color="text.disabled">
              none
            </Typography>
          ) : row.normalizedUrl === row.submittedUrl ? (
            'same'
          ) : (
            <Box component="span" sx={{ fontFamily: 'monospace', fontSize: '0.8125rem' }}>
              {row.normalizedUrl}
            </Box>
          )}
        </Field>
        <Field label="Resolved ATS">
          {row.resolvedAts ?? '—'}
          {' · '}
          <Typography component="span" variant="body2" color="text.secondary">
            Board token
          </Typography>{' '}
          {row.boardToken ?? (
            <Typography component="span" variant="body2" color="text.disabled">
              none
            </Typography>
          )}
        </Field>
        {row.companyId ? (
          <Field label="Company row">
            <Box component="span" sx={{ fontFamily: 'monospace', fontSize: '0.8125rem' }}>
              {row.companyId}
            </Box>{' '}
            {row.companyExists ? (
              <Chip size="small" variant="outlined" label={row.companyVisibility ?? 'present'} />
            ) : (
              // The board is gone, so the URL above is all that is left of it.
              <Chip size="small" variant="outlined" label="deleted" />
            )}
          </Field>
        ) : null}
        <Field label="Decided in">
          {row.decidedInS === null ? (
            <Typography component="span" variant="body2" color="text.disabled">
              not measurable
            </Typography>
          ) : (
            <strong>{formatDuration(row.decidedInS)}</strong>
          )}
        </Field>
        <Field label="First seen">
          {formatTimestamp(row.firstSeenAt)}
          {' · '}
          {row.auditRowCount} audit row{row.auditRowCount === 1 ? '' : 's'}
        </Field>
        <Field label="Raw outcome">
          <Box component="span" sx={{ fontFamily: 'monospace', fontSize: '0.8125rem' }}>
            {row.rawOutcome}
          </Box>
        </Field>
        {/* The verbatim `error_detail`, kept even when the checklist rendered —
            the split above is a convenience, this is the record. */}
        {row.errorDetail ? (
          <Field label="Error detail">
            <Box component="span" sx={{ fontFamily: 'monospace', fontSize: '0.8125rem' }}>
              {row.errorDetail}
            </Box>
          </Field>
        ) : null}
      </Box>
    </Box>
  );
}
