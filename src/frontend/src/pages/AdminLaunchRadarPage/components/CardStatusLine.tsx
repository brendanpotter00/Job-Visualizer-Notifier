import type { MouseEvent, ReactNode } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { LaunchRadarCard } from '../../../features/admin/launchRadarTypes';
import { RESPONSIVE } from '../../../config/responsive';
import { cardToggleId, formatShortDate, jobBoardHref, prHref, prLabel } from '../format';

/** Tighter action buttons on a phone, so the line fits a narrow card. */
const ACTION_SX = {
  px: RESPONSIVE.launchRadar.actionPaddingX,
  minWidth: RESPONSIVE.launchRadar.actionMinWidth,
} as const;

/** The lifecycle moves this line offers; `RadarCard` maps each to a PATCH. */
export type CardAction = 'save' | 'unsave' | 'archive' | 'restore';

interface CardStatusLineProps {
  card: LaunchRadarCard;
  expanded: boolean;
  /** Id of the collapsible body, for the toggle's aria-controls. */
  bodyId: string;
  onToggle: () => void;
  /**
   * True while this card's status request is in flight, and after it
   * succeeded: the card is leaving the list, so nothing on it may be pressed.
   */
  busy: boolean;
  onAction: (action: CardAction) => void;
  onDelete: () => void;
}

/**
 * The whole card header toggles the body on a mouse click, so every control in
 * it stops the click: it must do its own job and never also open the card.
 */
function stopToggle(event: MouseEvent) {
  event.stopPropagation();
}

/**
 * The right side's buttons for each tab, in order. Delete is separate. Read
 * with `?? []`: the list response is checked for a known status, but a status
 * this build does not know must render no actions, never crash the page.
 */
const ACTIONS: Record<LaunchRadarCard['status'], { action: CardAction; label: string }[]> = {
  new: [
    { action: 'save', label: 'Save' },
    { action: 'archive', label: 'Archive' },
  ],
  saved: [
    { action: 'unsave', label: 'Unsave' },
    { action: 'archive', label: 'Archive' },
  ],
  archived: [{ action: 'restore', label: 'Restore' }],
};

/**
 * One line under the scores. Left: "Already tracked" when the company is
 * already on the site, otherwise a "Job board" link to open its board by hand
 * (only an `http(s)` URL becomes a link); an archived card shows when it was
 * archived. Then, once the nightly loop opened the card's add-company PR, a
 * "View PR #N" link (on any tab: unsaving does not hide a PR that exists).
 * Right: the lifecycle actions for the card's tab (New: Save, Archive · Saved:
 * Unsave, Archive · Archived: Restore, Delete).
 *
 * Every button and link names the company in its accessible name ("Save
 * Lightfield", "Job board Lightfield"): a page holds 25 cards, and 25 buttons
 * all called "Save" are indistinguishable in a screen reader's controls list.
 */
export function CardStatusLine({
  card,
  expanded,
  bodyId,
  onToggle,
  busy,
  onAction,
  onDelete,
}: CardStatusLineProps) {
  let left: ReactNode = null;
  if (card.status === 'archived') {
    left = (
      <Typography component="span" variant="body2" color="text.secondary">
        Archived {formatShortDate(card.archivedAt)}
      </Typography>
    );
  } else if (card.trackedCompanyId) {
    left = (
      <Typography component="span" variant="body2" color="text.secondary">
        Already tracked
      </Typography>
    );
  } else {
    const board = jobBoardHref(card.ats, card.careersUrl);
    if (board) {
      left = (
        <Link
          href={board}
          target="_blank"
          rel="noopener noreferrer"
          onClick={stopToggle}
          variant="body2"
          color="text.secondary"
          aria-label={`Job board ${card.company}`}
        >
          Job board
        </Link>
      );
    }
  }

  const pr = prHref(card);
  const prText = prLabel(card);
  const prLink =
    pr && prText ? (
      <Link
        href={pr}
        target="_blank"
        rel="noopener noreferrer"
        onClick={stopToggle}
        variant="body2"
        color="text.secondary"
        aria-label={`${prText} ${card.company}`}
      >
        {prText}
      </Link>
    ) : null;

  return (
    // Left and right wrap as whole units: on a narrow card the actions drop
    // to their own line (still on the right) rather than "Job board" or
    // "Already tracked" breaking mid-label.
    <Box
      sx={{
        gridColumn: '1 / -1',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 1,
        mt: 1.25,
        pt: 1,
        borderTop: 1,
        borderColor: 'divider',
      }}
    >
      <Box sx={{ whiteSpace: 'nowrap' }}>
        {left}
        {left && prLink && (
          <Typography component="span" variant="body2" color="text.secondary" aria-hidden>
            {' · '}
          </Typography>
        )}
        {prLink}
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25, flexShrink: 0, ml: 'auto' }}>
        {(ACTIONS[card.status] ?? []).map(({ action, label }) => (
          <Button
            key={action}
            size="small"
            color="inherit"
            disabled={busy}
            aria-label={`${label} ${card.company}`}
            sx={ACTION_SX}
            onClick={(e) => {
              stopToggle(e);
              onAction(action);
            }}
          >
            {label}
          </Button>
        ))}
        {card.status === 'archived' && (
          <Button
            size="small"
            color="error"
            disabled={busy}
            aria-label={`Delete ${card.company}`}
            sx={ACTION_SX}
            onClick={(e) => {
              stopToggle(e);
              onDelete();
            }}
          >
            Delete
          </Button>
        )}
        {/* The keyboard / screen-reader toggle. The header's own click is a
            mouse convenience; this button is the accessible control. */}
        <IconButton
          id={cardToggleId(card.id)}
          size="small"
          aria-expanded={expanded}
          aria-controls={bodyId}
          aria-label={`${expanded ? 'Hide' : 'Show'} details for ${card.company}`}
          onClick={(e) => {
            stopToggle(e);
            onToggle();
          }}
        >
          <ExpandMoreIcon
            fontSize="small"
            sx={{
              color: 'text.disabled',
              transition: 'transform 150ms',
              transform: expanded ? 'rotate(180deg)' : 'none',
            }}
          />
        </IconButton>
      </Box>
    </Box>
  );
}
