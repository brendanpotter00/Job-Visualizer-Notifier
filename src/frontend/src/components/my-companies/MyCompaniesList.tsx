import { useEffect, useRef, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import IconButton from '@mui/material/IconButton';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import CloseIcon from '@mui/icons-material/Close';
import RenameIcon from '@mui/icons-material/DriveFileRenameOutlineOutlined';
import { LoadingState } from '../shared/LoadingIndicator';
import { ErrorState } from '../shared/ErrorDisplay';
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
import { AddCompanyHowTo } from './AddCompanyHowTo';
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

/**
 * One company row: name → trend page, health badge, count, last-fetched, remove.
 *
 * THE WHOLE CARD OPENS THE COMPANY, and that is what makes the two icons in it a trap
 * rather than a detail. A card wrapped in a `CardActionArea` (or in an `<a>`) with a
 * pencil and an X inside it is NESTED INTERACTIVE CONTENT: a `<button>` inside an
 * `<a>` is invalid HTML, screen readers disagree about what to announce, and in
 * practice the icons end up navigating instead of doing their job.
 *
 * So this uses a STRETCHED LINK instead. The card is `position: relative`, the company
 * name stays an ordinary link, and its `::after` is stretched to `inset: 0` so the
 * whole card is that one link's hit area. The pencil and the X are SIBLINGS of the
 * name, raised to `z-index: 2`, so a press on either never reaches the overlay
 * underneath. The DOM has no button inside a link and no link inside a button.
 *
 * KEYBOARD ORDER IS NAME, EDIT, REMOVE, because that is the DOM order — which is also
 * why the two icons sit on the name's row rather than in a column of their own beside
 * the metadata. The board link is last, after them, for the same reason.
 *
 * TWO COSTS, both real and neither stylable away. (1) The overlay sits over the card's
 * own text, so the name, the count and the freshness line can no longer be selected
 * with the mouse, and the exact-instant `title` tooltip on the freshness line no longer
 * opens on hover (the attribute is still there, and the phrase beside it is what the
 * list is scanned for). (2) Anything raised ABOVE the overlay punches a hole in the
 * click target — that is the board link, the checklist and the match banner, each of
 * which is interactive in its own right and each of which is commented where it sits.
 */
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
    <Paper
      variant="outlined"
      // `position: relative` is not decoration: it is what the name link's stretched
      // `::after` resolves against, and therefore what makes the card the click target.
      sx={{ p: 2, position: 'relative' }}
      data-testid="my-company-row"
    >
      {/* THE NAME ROW: name, then the two actions. One flex row, not a two-column
          layout, so the DOM order and the reading order and the tab order are the same
          order. The pencil sits beside the name (it acts on the name); the X is pushed
          to the far edge, away from it, because the two are not a pair. */}
      <Box
        sx={{
          display: 'flex',
          // While the editor is open the row is two stacked controls against one icon,
          // so the X lines up with the top of the field rather than floating against
          // the middle of it.
          alignItems: isRenaming ? 'flex-start' : 'center',
          gap: 0.5,
          minWidth: 0,
        }}
      >
        {isRenaming ? (
          <Box sx={{ flex: '1 1 auto', minWidth: 0 }}>
            <CompanyNameEditor
              company={company}
              onClose={() => setIsRenaming(false)}
              returnFocusTo={renameButtonRef}
            />
          </Box>
        ) : (
          <>
            <Link
              component={RouterLink}
              to={buildMyCompanyDetailPath(company.id)}
              variant="h6"
              data-testid="my-company-link"
              // Same wrap-anywhere rule the board link below already uses. A user can
              // now type the name, so "a name with no spaces in it" stopped being
              // hypothetical — and the house choice here is to wrap, never to ellipsise
              // a thing the reader cannot then hover to read in full.
              sx={{
                display: 'inline-block',
                minWidth: 0,
                overflowWrap: 'anywhere',
                // THE STRETCHED LINK. This transparent overlay — a pseudo-element of the
                // link, so it needs no extra DOM and cannot nest anything — is what makes
                // the whole card open this company. It is UNMOUNTED WITH THE LINK while a
                // rename is open, which is a free correctness win: you cannot fat-finger
                // your way onto another page while you are typing a name.
                '&::after': {
                  content: '""',
                  position: 'absolute',
                  inset: 0,
                  borderRadius: 1,
                  zIndex: 1,
                },
              }}
            >
              {company.displayName}
            </Link>
            {/* NOT THE FILLED PENCIL, which the owner rejected on sight. This is the
                rename glyph (a nib over the line it is writing on), outlined rather than
                solid so it sits at the weight of the metadata instead of competing with
                the name beside it, and it says "rename this text" rather than the pencil's
                broader "edit this thing" — the only thing this control changes is the
                display name. Both icons are drawn in `text.secondary` and only take a
                colour under the pointer, which is the actual fix for "these buttons are
                pretty nasty": what was two filled controls is now two grey marks.

                HIDDEN WHILE EDITING, not disabled — a deliberate deviation from the text
                button this replaced. An unlabelled icon sitting greyed out beside an open
                text field is clutter, and the open field is already the clearest possible
                statement that renaming is in progress. */}
            <IconButton
              ref={renameButtonRef}
              onClick={() => setIsRenaming(true)}
              // The row's own name is in the label because a screen-reader user listing
              // the page's buttons otherwise hears "Rename" once per board — and with no
              // visible text on the control, this label is now the ONLY name it has.
              aria-label={`Rename ${company.displayName}`}
              data-testid="my-company-rename"
              // Raised above the stretched overlay so the press acts instead of navigating.
              sx={{
                position: 'relative',
                zIndex: 2,
                flexShrink: 0,
                color: 'text.secondary',
                '&:hover': { color: 'text.primary' },
              }}
            >
              <RenameIcon fontSize="small" />
            </IconButton>
          </>
        )}
        {/* The X stays put during a rename: abandoning a rename by removing the company
            is a thing people genuinely try. It opens the confirmation below — this is
            still the last screen between the user and an irreversible delete. */}
        <IconButton
          onClick={() => onRemove(company)}
          aria-label={`Remove ${company.displayName}`}
          data-testid="my-company-remove"
          sx={{
            position: 'relative',
            zIndex: 2,
            flexShrink: 0,
            ml: 'auto',
            color: 'text.secondary',
            '&:hover': { color: 'error.main' },
          }}
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* THE METADATA LINE, below the name row and under the stretched overlay: the
          facts about this board, none of which is a control except the board link at
          the end of it. */}
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
        <Typography variant="body2" color="text.secondary" title={lastFetched.exactAt ?? undefined}>
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
            // RAISED, and it is the one hole in the click target worth paying for.
            // It is the only way to look at a board that has started serving dead
            // job links, which is the reason it is on the row at all — deleting it
            // to make the card a tidier target would trade a diagnostic for a
            // geometry. The cost is honest: a user aiming at "open this company"
            // can land on the ATS's own site instead.
            sx={{ position: 'relative', zIndex: 2, minWidth: 0, overflowWrap: 'anywhere' }}
          >
            {boardLink.label} ↗
          </Link>
        ) : null}
      </Stack>

      {/* Everything below is interactive in its own right — an expander, and an alert
          with its own buttons — so it is raised above the stretched overlay as a block.
          Without this the card's click target would swallow the checklist's own
          controls. `position: relative` is what makes `zIndex` apply at all. */}
      <Box sx={{ position: 'relative', zIndex: 2 }}>
        {/* `receivedAt` is not decoration here: the live view treats `liveViewUrl` as a
            claim that EXPIRES, and this is the only thing that renews it. See
            `DiscoveryChecklist`'s `LIVE_VIEW_TRUST_MS`. */}
        {showChecklist && <DiscoveryChecklist company={company} receivedAt={receivedAt} />}

        {/* "This looks like Spotify, which we already track." Renders only when the
            backend actually found an overlap, which is almost never — and the component
            owns its own dismissal, so the row needs no state for it. `onRemove` is the
            SAME handler the row's X uses, so the banner's remove goes through the
            ordinary confirmation dialog rather than inventing a shortcut. */}
        <PublicBoardMatchBanner company={company} onRemove={onRemove} />
      </Box>
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
          We couldn&apos;t refresh just now. This is what we last loaded.
        </Alert>
      ) : null}

      <Typography variant="h6" component="h2" gutterBottom>
        Companies you&apos;re tracking
      </Typography>

      {/* THE HOW-TO IS THE EMPTY STATE. There is no separate "no companies yet" screen
          and no separate how-to section: they are the same block. A user with nothing
          tracked sees the explanation where an icon and two grey lines used to sit, and
          the moment they have one company their list is there instead and the
          explanation is one text link away (`MyCompaniesPage`, "How it works").

          `rows.length === 0` is safe as the gate ONLY because the `isLoading` branch
          above already returned: on a first load the query is not settled and this
          would otherwise be briefly true for every returning user, who would watch a
          three-step tutorial flash on screen and vanish. */}
      {rows.length === 0 ? (
        <AddCompanyHowTo srOnlyLine="No companies yet" />
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
              ? `Removing “${pendingRemoval.displayName}” deletes every job collected for it: ${
                  pendingRemoval.openJobCount > 0
                    ? `the ${pendingRemoval.openJobCount.toLocaleString()} open now, plus the closed ones behind its hiring chart`
                    : 'both the open ones and the closed ones behind its hiring chart'
                }. This is a delete, not a pause. Nothing is kept, and adding the board again starts the chart over from zero.`
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
