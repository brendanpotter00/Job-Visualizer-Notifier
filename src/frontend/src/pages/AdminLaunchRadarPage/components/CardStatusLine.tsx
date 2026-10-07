import type { MouseEvent, ReactNode } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { LaunchRadarCard } from '../../../features/admin/launchRadarTypes';
import { formatShortDate } from '../format';

interface CardStatusLineProps {
  card: LaunchRadarCard;
  expanded: boolean;
  /** Id of the collapsible body, for the toggle's aria-controls. */
  bodyId: string;
  onToggle: () => void;
  /** True while this card's archive/restore request is in flight. */
  busy: boolean;
  onArchive: () => void;
  onRestore: () => void;
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
 * One line under the scores. Left: what the admin can do about this company
 * (merge the add-company PR, nothing because it is already tracked, or open
 * the job board by hand). Right: the lifecycle actions for the current tab.
 */
export function CardStatusLine({
  card,
  expanded,
  bodyId,
  onToggle,
  busy,
  onArchive,
  onRestore,
  onDelete,
}: CardStatusLineProps) {
  let left: ReactNode;
  if (card.status === 'archived') {
    left = (
      <Typography component="span" variant="body2" color="text.secondary">
        Archived {formatShortDate(card.archivedAt)}
      </Typography>
    );
  } else if (card.prUrl) {
    left = (
      <Link
        href={card.prUrl}
        target="_blank"
        rel="noopener noreferrer"
        onClick={stopToggle}
        variant="body2"
        sx={{ color: 'success.main', fontWeight: 500 }}
      >
        Add-company PR ready
      </Link>
    );
  } else if (card.trackedCompanyId) {
    left = (
      <Typography component="span" variant="body2" color="text.secondary">
        Already tracked
      </Typography>
    );
  } else {
    const board = card.ats.boardUrl ?? card.careersUrl;
    left = (
      <Typography component="span" variant="body2" color="text.secondary">
        No PR
        {board && (
          <>
            {' · '}
            <Link
              href={board}
              target="_blank"
              rel="noopener noreferrer"
              onClick={stopToggle}
              color="inherit"
            >
              Open job board
            </Link>
          </>
        )}
      </Typography>
    );
  }

  return (
    <Box
      sx={{
        gridColumn: '2 / -1',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 1,
        mt: 1.25,
        pt: 1,
        borderTop: 1,
        borderColor: 'divider',
      }}
    >
      <Box sx={{ minWidth: 0 }}>{left}</Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25, flexShrink: 0 }}>
        {card.status === 'new' ? (
          <Button
            size="small"
            color="inherit"
            disabled={busy}
            onClick={(e) => {
              stopToggle(e);
              onArchive();
            }}
          >
            Archive
          </Button>
        ) : (
          <>
            <Button
              size="small"
              color="inherit"
              disabled={busy}
              onClick={(e) => {
                stopToggle(e);
                onRestore();
              }}
            >
              Restore
            </Button>
            <Button
              size="small"
              color="error"
              disabled={busy}
              onClick={(e) => {
                stopToggle(e);
                onDelete();
              }}
            >
              Delete
            </Button>
          </>
        )}
        {/* The keyboard / screen-reader toggle. The header's own click is a
            mouse convenience; this button is the accessible control. */}
        <IconButton
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
