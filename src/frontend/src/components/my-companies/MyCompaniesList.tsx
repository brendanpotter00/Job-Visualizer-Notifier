import { useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import EditIcon from '@mui/icons-material/Edit';
import { LoadingState } from '../shared/LoadingIndicator';
import { ErrorState, EmptyState } from '../shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { buildMyCompanyDetailPath } from '../../config/routes';
import { CUSTOM_COMPANIES_CONFIG } from '../../config/customCompanies';
import {
  COMPANY_NAME_MAX_LENGTH,
  describeRenameError,
  useGetUserCompaniesQuery,
  useRemoveUserCompanyMutation,
  useRenameUserCompanyMutation,
  type UserCompany,
} from '../../features/userCompanies/userCompaniesApi';
import {
  DISCOVERY_POLL_INTERVAL_MS,
  describeCompanyHealth,
  describeLastFetched,
  shouldShowDiscovery,
  sourceBoardLabel,
  sourceBoardUrl,
} from './companyHealth';
import { DiscoveryChecklist } from './DiscoveryChecklist';
import { PublicBoardMatchBanner } from './PublicBoardMatchBanner';

/** Poll cadence while any row is still an empty, unverified board. */
const POLL_INTERVAL_MS = 15_000;

// The faster discovery cadence (`DISCOVERY_POLL_INTERVAL_MS`) is imported from
// `companyHealth` rather than declared here: it is still the SAME query and the same
// component (DECISION D2: extend the existing poll, never add a second channel), but the
// live view's trust window is derived from it, and the two must not drift. See its
// docstring for why it moved.

/**
 * How stale a `discovering` row's last progress write may be before we stop believing
 * anything is still running behind it.
 *
 * A row only leaves `discovering` when the task persists an outcome, and that task is
 * `retry=1`. Three documented paths leave it there for good: the discovery flag flipped
 * off between enqueue and execution, no worker draining the `custom_discovery` queue, and
 * the SIGKILL/OOM "WEDGED-ROW CAVEAT" the task itself carries a TODO for. Without a bound,
 * such a row would poll every 4s for as long as the tab stays open — ~900 requests/hour,
 * each running a per-row `count(*)` — while the user watches a checklist frozen mid-step.
 * Past this window the row falls back to the ordinary 15s settling cadence, so a wedged
 * row costs no more than it did before the checklist existed. Comfortably above the task's
 * own 240s cap, because a run whose progress writes are all failing still updates nothing
 * until it terminates — and being slow there is a cadence choice, not a correctness one.
 */
const DISCOVERY_STALE_AFTER_MS = 5 * 60_000;

/**
 * Is this row a discovery we have recent evidence is still moving?
 *
 * `discovery.updatedAt` is stamped by every progress write, which is exactly the signal
 * the backend emits it for. A missing or unparseable timestamp reads as NOT live (an
 * older blob shouldn't buy the fast cadence); a timestamp in the future does read as live,
 * since that is clock skew between the server and this browser, not staleness.
 *
 * `receivedAt` is RTK Query's `fulfilledTimeStamp`, NOT `Date.now()`: reading the clock
 * during render is lint-blocked as impure, and "how stale was this row when the payload
 * carrying it arrived" is the more honest question anyway. It advances on every poll, so
 * a run that stops writing ages out on its own.
 */
function isDiscoveryLive(company: UserCompany, receivedAt: number): boolean {
  if (company.healthState !== 'discovering') return false;
  const updatedAt = company.discovery?.updatedAt;
  if (!updatedAt) return false;
  const writtenAt = Date.parse(updatedAt);
  if (Number.isNaN(writtenAt)) return false;
  return writtenAt >= receivedAt - DISCOVERY_STALE_AFTER_MS;
}

/**
 * A row is "still settling" if its first harvest hasn't landed yet, so the list
 * should keep polling for it. Two cases:
 *  - `discovering` — the one-time capture setup is still running (E7 capture
 *    pivot); the row flips to tracked or `refused` when it finishes.
 *  - `unverified` with no jobs yet — a brand-new tracked board whose first
 *    harvest hasn't run.
 */
function isStillSettling(company: UserCompany): boolean {
  return (
    company.healthState === 'discovering' ||
    (company.healthState === 'unverified' && company.openJobCount === 0)
  );
}

/**
 * How often to re-poll, given the rows we have: nothing while everything is settled,
 * the fast cadence while a discovery is demonstrably mid-run, the slow one otherwise.
 *
 * Pure — `receivedAt` is passed in rather than read from the clock — and computed from
 * the rows rather than held in state, so `CompaniesPoller` stays a plain-prop component
 * (see below). Re-evaluated on every render, so a run that goes quiet drops itself to
 * the slow cadence on the next poll without anything having to notice.
 */
function pollIntervalFor(rows: UserCompany[], receivedAt: number): number {
  if (
    CUSTOM_COMPANIES_CONFIG.isDiscoveryProgressEnabled &&
    rows.some((company) => isDiscoveryLive(company, receivedAt))
  ) {
    return DISCOVERY_POLL_INTERVAL_MS;
  }
  return rows.some(isStillSettling) ? POLL_INTERVAL_MS : 0;
}

/**
 * Adds (only) a polling subscription to the shared `getUserCompanies` cache at
 * `intervalMs` (0 = off). Split into its own component so the poll cadence is
 * derived from a plain prop — no effect, no setState-in-render, no ref-in-render
 * (all three are lint-blocked). Both this and the list subscribe to the same
 * query key; RTK Query merges them and polls at this subscriber's interval.
 */
function CompaniesPoller({ intervalMs }: { intervalMs: number }) {
  useGetUserCompaniesQuery(undefined, { pollingInterval: intervalMs });
  return null;
}

/**
 * Inline rename for one board's name. Renders in place of the title link.
 *
 * A PENDING STATE, NOT AN OPTIMISTIC PATCH. The failure mode worth designing against is
 * a rename that looks saved and then quietly reverts, and the only shape that cannot do
 * that is one which does not claim success until the server agrees. The round trip is a
 * single local UPDATE, so the wait is a flicker; a patch-then-undo would trade that for
 * a visible take-back.
 *
 * FOCUS GOES BACK WHERE IT CAME FROM. Save and Cancel both unmount this, and without the
 * effect below focus would land on `<body>` — a keyboard user would be dropped at the top
 * of the page after renaming a row halfway down it. Nothing is trapped: this is ordinary
 * inline markup, so Tab leaves in both directions at all times.
 */
function CompanyNameEditor({
  company,
  onClose,
  returnFocusTo,
}: {
  company: UserCompany;
  onClose: () => void;
  returnFocusTo: React.RefObject<HTMLButtonElement | null>;
}) {
  const [draft, setDraft] = useState(company.displayName);
  const [error, setError] = useState<string | null>(null);
  const [renameUserCompany, { isLoading }] = useRenameUserCompanyMutation();
  const trimmed = draft.trim();

  // On unmount — which is what Save and Cancel both do — hand focus back to the button
  // that opened this.
  useEffect(() => () => returnFocusTo.current?.focus(), [returnFocusTo]);

  const commit = async () => {
    if (!trimmed || isLoading) return;
    // Nothing to save. Closing without a request is not a shortcut: an unchanged name
    // is not a change, and a no-op write would still bill a rate-limit slot.
    if (trimmed === company.displayName) {
      onClose();
      return;
    }
    setError(null);
    try {
      await renameUserCompany({ id: company.id, displayName: trimmed }).unwrap();
      onClose();
    } catch (err) {
      // Stay open with the draft intact. Closing on failure would throw away what they
      // typed and leave the old name on screen with no explanation.
      setError(describeRenameError(err));
    }
  };

  return (
    <Box
      component="form"
      onSubmit={(event: React.FormEvent) => {
        event.preventDefault();
        void commit();
      }}
      onKeyDown={(event: React.KeyboardEvent) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems="flex-start">
        <TextField
          // A real <label>, not a placeholder: a placeholder disappears the moment
          // anyone types, which is exactly when a screen reader needs it most.
          label="Company name"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          size="small"
          fullWidth
          autoFocus
          disabled={isLoading}
          error={Boolean(error)}
          // MUI wires this to the input with aria-describedby, so the failure is
          // announced rather than merely drawn.
          helperText={error ?? ' '}
          slotProps={{ htmlInput: { maxLength: COMPANY_NAME_MAX_LENGTH } }}
          data-testid="my-company-name-input"
        />
        <Stack direction="row" spacing={1} sx={{ flexShrink: 0, mt: { sm: 0.5 } }}>
          <Button
            type="submit"
            variant="contained"
            size="small"
            disabled={!trimmed || isLoading}
            data-testid="my-company-name-save"
          >
            {isLoading ? 'Saving…' : 'Save'}
          </Button>
          <Button
            type="button"
            size="small"
            onClick={onClose}
            disabled={isLoading}
            data-testid="my-company-name-cancel"
          >
            Cancel
          </Button>
        </Stack>
      </Stack>
    </Box>
  );
}

/** One company row: name → trend page, health badge, count, last-fetched, remove. */
function CompanyRow({
  company,
  onRemove,
  receivedAt,
}: {
  company: UserCompany;
  onRemove: (company: UserCompany) => void;
  /**
   * `fulfilledTimeStamp` — when THIS payload landed, threaded down so the freshness line
   * can be relative without any component reading the clock during render (lint-blocked
   * as impure; the same reason `isDiscoveryLive` takes it as an argument).
   */
  receivedAt: number;
}) {
  const [isRenaming, setIsRenaming] = useState(false);
  // Where focus goes when the editor closes. Held here rather than inside the editor
  // because the button it points at is unmounted-and-remounted around it.
  const renameButtonRef = useRef<HTMLButtonElement | null>(null);
  const badge = describeCompanyHealth(company);
  const lastFetched = describeLastFetched(company, receivedAt);
  // The link and its text are resolved together, and BOTH must exist: a label we cannot
  // derive from the very url we are about to link to means the two could disagree, and a
  // link whose text is not its destination is the one kind of link nobody should ship.
  const boardUrl = sourceBoardUrl(company);
  const boardLabel = boardUrl ? sourceBoardLabel(boardUrl) : null;
  const boardLink = boardUrl && boardLabel ? { url: boardUrl, label: boardLabel } : null;
  // Flag OFF must render byte-for-byte what shipped before the checklist existed, so
  // the gate is here rather than inside the component: no extra element, no wrapper.
  const showChecklist =
    CUSTOM_COMPANIES_CONFIG.isDiscoveryProgressEnabled && shouldShowDiscovery(company);
  return (
    <Paper variant="outlined" sx={{ p: 2 }} data-testid="my-company-row">
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1.5}
        // TOP-aligned on sm+, where it used to be centred. The left column is two lines
        // (name + metadata) and the actions are one, so centring floated the buttons
        // against the gap between them and lined them up with nothing. Level with the
        // name is the line a reader is already on when they decide to act.
        alignItems="flex-start"
        justifyContent="space-between"
      >
        {/* `flexGrow` is what makes `minWidth: 0` do anything: without it the column is
            sized by its content, so a long name pushed the buttons off the card instead
            of wrapping inside it. */}
        <Box sx={{ minWidth: 0, flexGrow: 1, width: '100%' }}>
          {isRenaming ? (
            <CompanyNameEditor
              company={company}
              onClose={() => setIsRenaming(false)}
              returnFocusTo={renameButtonRef}
            />
          ) : (
            <Link
              component={RouterLink}
              to={buildMyCompanyDetailPath(company.id)}
              variant="h6"
              data-testid="my-company-link"
              // Same wrap-anywhere rule the board link below already uses. A user can
              // now type the name, so "a name with no spaces in it" stopped being
              // hypothetical — and the house choice here is to wrap, never to ellipsise
              // a thing the reader cannot then hover to read in full.
              sx={{ display: 'inline-block', minWidth: 0, overflowWrap: 'anywhere' }}
            >
              {company.displayName}
            </Link>
          )}
          <Stack
            direction="row"
            alignItems="center"
            flexWrap="wrap"
            useFlexGap
            // A wider COLUMN gap and a tighter ROW gap, replacing one uniform 8px. The
            // facts on this line wrap onto two lines at narrow widths, and at 8px each
            // way the second line sat close enough to the first to read as part of it.
            sx={{ mt: 0.75, columnGap: 1.5, rowGap: 0.25 }}
          >
            {/* `variant` carries the one qualifier colour is not allowed to carry: a
                hollow green chip is a board we track incompletely, and it must not
                borrow the amber that means "something needs you" for a permanent
                property of someone else's API. See `describeCompanyHealth`. */}
            <Chip
              size="small"
              color={badge.color}
              variant={badge.variant ?? 'filled'}
              label={badge.label}
            />
            {/* THE COUNT IS THE NUMBER PEOPLE SCAN THIS LIST FOR, and it used to be one
                of four same-weight secondary phrases — so finding it meant reading the
                whole line. Primary colour and a half-step of weight lift it out of the
                metadata without making it shout.

                Deliberately NOT a nested <span> around just the digits, which is the
                obvious way to two-tone this: Testing Library matches an element on its
                DIRECT text children, so wrapping the number splits "12 open jobs" across
                two elements and every `getByText(/12 open jobs/)` in the suite stops
                matching. A styling choice is not worth rewriting assertions about what
                the user reads. */}
            <Typography variant="body2" color="text.primary" sx={{ fontWeight: 500 }}>
              {company.openJobCount.toLocaleString()}{' '}
              {company.openJobCount === 1 ? 'open job' : 'open jobs'}
            </Typography>
            {/* "Last fetched", never "Last checked": the timestamp behind it only moves
                on a run that did NOT fail, so a board failing nightly wore a stamp that
                said nobody had looked. The exact instant moves to `title` — the phrase
                is for scanning the list, the tooltip is for the one row you care about.
                See `describeLastFetched`. */}
            <Typography
              variant="body2"
              color="text.secondary"
              title={lastFetched.exactAt ?? undefined}
            >
              {lastFetched.label}
            </Typography>
            {/* THE BOARD WE BUILT THIS FROM. The row said what we found and how fresh it
                is and never once said where it came from, so a board that started
                serving dead job links could only be checked from the database.
                It sits at the END of the metadata line, after the facts about the data,
                because it is provenance rather than status — and it wraps off onto its
                own line first on a narrow screen, which is the right thing to lose.
                Same short-form/`title` division as the freshness line above it. Renders
                nothing at all when we cannot build an HONEST url (Workday and Eightfold
                keep their real host in `provider_config`, which this payload does not
                carry) — a confident link to a 404 would be worse than the gap. */}
            {boardLink ? (
              <Link
                href={boardLink.url}
                target="_blank"
                rel="noopener noreferrer"
                variant="body2"
                color="text.secondary"
                underline="hover"
                title={boardLink.url}
                data-testid="my-company-board-link"
                sx={{ minWidth: 0, overflowWrap: 'anywhere' }}
              >
                {boardLink.label} ↗
              </Link>
            ) : null}
          </Stack>
        </Box>

        {/* The two row actions, grouped and pinned. `flexShrink: 0` is what keeps a long
            company name from squeezing them; before there was one button and nothing to
            squeeze it against. Rename is a plain button and Remove keeps `color="error"`,
            so the destructive one is still the only coloured thing here. */}
        <Stack direction="row" spacing={0.5} sx={{ flexShrink: 0 }}>
          <Button
            ref={renameButtonRef}
            size="small"
            startIcon={<EditIcon />}
            onClick={() => setIsRenaming(true)}
            disabled={isRenaming}
            // The row's own name is in the label because a screen-reader user listing
            // the page's buttons otherwise hears "Rename" once per board.
            aria-label={`Rename ${company.displayName}`}
            data-testid="my-company-rename"
          >
            Rename
          </Button>
          <Button
            color="error"
            size="small"
            onClick={() => onRemove(company)}
            aria-label={`Remove ${company.displayName}`}
            data-testid="my-company-remove"
          >
            Remove
          </Button>
        </Stack>
      </Stack>

      {/* `receivedAt` is not decoration here: the live view treats `liveViewUrl` as a
          claim that EXPIRES, and this is the only thing that renews it. See
          `DiscoveryChecklist`'s `LIVE_VIEW_TRUST_MS`. */}
      {showChecklist && <DiscoveryChecklist company={company} receivedAt={receivedAt} />}

      {/* "This looks like Spotify, which we already track." Renders only when the backend
          actually found an overlap, which is almost never — and the component owns its own
          dismissal, so the row needs no state for it. `onRemove` is the SAME handler the
          row's Remove button uses, so the banner's remove goes through the ordinary
          confirmation dialog rather than inventing a shortcut. */}
      <PublicBoardMatchBanner company={company} onRemove={onRemove} />
    </Paper>
  );
}

/**
 * The signed-in user's tracked companies, rendered below the resolve form.
 *
 * Only mounted behind the feature flag (its parent page is route-gated), so it
 * makes no network call in a flag-off build. Polls `getUserCompanies` every 15s
 * *only* while some row is an empty unverified board — a brand-new add whose
 * first harvest hasn't landed yet — and stops as soon as every row has jobs or
 * leaves the unverified state, so a settled list is not polled forever. A
 * discovery whose progress blob is still moving gets the faster cadence instead
 * (see `pollIntervalFor`), bounded by staleness so a wedged row cannot hold it.
 */
export function MyCompaniesList() {
  const {
    // The whole `{ companies, quota }` envelope. The list only wants the rows; the
    // quota is read by the page, off this same cache entry.
    data,
    isLoading,
    isError,
    error,
    refetch,
    // When the payload we are rendering actually landed. Stands in for `Date.now()`,
    // which cannot be read during render — see `isDiscoveryLive`.
    fulfilledTimeStamp,
  } = useGetUserCompaniesQuery();
  const companies = data?.companies;

  const [removeUserCompany] = useRemoveUserCompanyMutation();
  const [pendingRemoval, setPendingRemoval] = useState<UserCompany | null>(null);

  const confirmRemoval = () => {
    if (pendingRemoval) {
      void removeUserCompany(pendingRemoval.id);
    }
    setPendingRemoval(null);
  };

  if (isLoading) {
    return <LoadingState minHeight={120} caption="Loading your companies…" />;
  }

  // ONLY when there is nothing to show. RTK Query keeps `data` from the last good fetch
  // and still flips the entry to rejected, so taking this branch on every `isError` let
  // one transient 502 on a *poll* delete every row — and unmount `CompaniesPoller` with
  // them, so auto-refresh never resumed without a manual Retry. That lands hardest on a
  // mid-run discovery, the one screen whose entire point is being live.
  if (isError && !companies) {
    return (
      <ErrorState
        inline
        message={extractErrorMessage(error, "We couldn't load your companies.")}
        onRetry={() => void refetch()}
      />
    );
  }

  const rows = companies ?? [];

  return (
    <Box>
      {/* Auto-refresh while any brand-new board hasn't reported jobs yet — faster
          while a discovery is mid-run so its checklist reads as live. */}
      <CompaniesPoller intervalMs={pollIntervalFor(rows, fulfilledTimeStamp ?? 0)} />

      {/* A failed refresh over a list we already have: say so, keep the list, keep
          polling. The next tick usually fixes it without the user doing anything. */}
      {isError ? (
        <Alert
          severity="warning"
          sx={{ mb: 1.5 }}
          data-testid="my-companies-refresh-warning"
          action={
            <Button color="inherit" size="small" onClick={() => void refetch()}>
              Retry
            </Button>
          }
        >
          We couldn&apos;t refresh just now — showing what we last loaded.
        </Alert>
      ) : null}

      <Typography variant="h6" component="h2" gutterBottom>
        Companies you&apos;re tracking
      </Typography>

      {rows.length === 0 ? (
        <EmptyState
          title="No companies yet"
          // Names the ONE action, not the branch it might take. The old copy told the
          // user to press "Track this company" — a button that never appears on the
          // discovery path, which is the path anything not on a supported board takes.
          message="Paste a careers URL above to start tracking a company."
        />
      ) : (
        <Stack spacing={1.5} data-testid="my-companies-list">
          {rows.map((company) => (
            <CompanyRow
              key={company.id}
              company={company}
              onRemove={setPendingRemoval}
              receivedAt={fulfilledTimeStamp ?? 0}
            />
          ))}
        </Stack>
      )}

      {/*
        THE COPY HAS TO NAME THE DELETE. This dialog confirms
        `DELETE /api/users/companies/{id}` → `custom_companies_service.remove_owned_company`,
        which is not "stop collecting from here on": it runs
        `DELETE FROM job_listings WHERE source_id = 'custom:<id>'` plus the same for the
        board's tags, enrichment, location links, harvests and scrape runs, and drops the
        company row. The previous wording — the history "will no longer be collected for
        you" — describes a pause, which is the one thing this is not, and it was the last
        screen between the user and an irreversible delete of everything the board had
        gathered. Re-adding the same URL mints a NEW id and a new empty namespace, so the
        chart genuinely starts at zero.

        The open count is named because it is the only concrete size the user has for what
        they are about to lose; it is a floor, not a total — the closed rows behind the
        hiring chart go too, and there is no count for those on this payload.
      */}
      <Dialog open={pendingRemoval !== null} onClose={() => setPendingRemoval(null)}>
        <DialogTitle>Delete this company and its job history?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            {pendingRemoval
              ? `Removing “${pendingRemoval.displayName}” deletes every job collected for it—${
                  pendingRemoval.openJobCount > 0
                    ? `the ${pendingRemoval.openJobCount.toLocaleString()} open now, plus the closed ones behind its hiring chart`
                    : 'both the open ones and the closed ones behind its hiring chart'
                }. This is a delete, not a pause: nothing is kept, and adding the board again starts the chart over from zero.`
              : ''}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingRemoval(null)}>Cancel</Button>
          <Button color="error" onClick={confirmRemoval} data-testid="my-company-remove-confirm">
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
