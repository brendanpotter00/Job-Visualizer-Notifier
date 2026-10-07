import { useState } from 'react';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import { useSetLaunchRadarCardStatusMutation } from '../../../features/admin/adminApi';
import {
  DEFAULT_LAUNCH_RADAR_SORT,
  type LaunchRadarCard,
  type LaunchRadarSort,
  type LaunchRadarStatus,
} from '../../../features/admin/launchRadarTypes';
import { extractErrorMessage } from '../../../lib/errors';
import { RESPONSIVE } from '../../../config/responsive';
import { safeHttpUrl, scoreEmphasis } from '../format';
import { CardBody } from './CardBody';
import { CardStatusLine, type CardAction } from './CardStatusLine';
import { EventLine } from './EventLine';
import { ScoreBadge } from './ScoreBadge';

/** Each status-line action, as the PATCH it sends and its error fallback. */
const ACTION_REQUEST: Record<CardAction, { status: LaunchRadarStatus; failed: string }> = {
  save: { status: 'saved', failed: 'Failed to save the card' },
  unsave: { status: 'new', failed: 'Failed to unsave the card' },
  archive: { status: 'archived', failed: 'Failed to archive the card' },
  restore: { status: 'new', failed: 'Failed to restore the card' },
};

/**
 * The site after the company name: inline beside it from sm up; on a phone,
 * where the name shares its row with the scores, on its own line under it
 * (sized to its text, so the empty space beside it still toggles the card).
 */
const DOMAIN_SX = {
  display: { xs: 'block', sm: 'inline' },
  width: { xs: 'fit-content', sm: 'auto' },
  maxWidth: '100%',
  ml: RESPONSIVE.launchRadar.domainMarginLeft,
  fontSize: 12,
  fontWeight: 400,
} as const;

interface RadarCardProps {
  card: LaunchRadarCard;
  /** The list's sort. Sorted by Talent or VC, that score reads first on the card. */
  sort?: LaunchRadarSort;
  /** Opens the page's single confirm dialog; deleting is never one click. */
  onRequestDelete: (card: LaunchRadarCard) => void;
  /**
   * Called once a status change succeeded. The card has then left this tab
   * (the cache drops it at once), so the page can move focus and announce it.
   */
  onLeave?: (card: LaunchRadarCard, action: CardAction) => void;
}

/**
 * One company the loop found. Closed: name + site, one-liner, the event and
 * its announcement link, Talent and VC scores, and one status line with the
 * lifecycle actions. Open: `CardBody`, aligned under the name.
 */
export function RadarCard({
  card,
  sort = DEFAULT_LAUNCH_RADAR_SORT,
  onRequestDelete,
  onLeave,
}: RadarCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [setStatus, { isLoading, isSuccess, error }] = useSetLaunchRadarCardStatusMutation();
  // The action behind the current `error`, for the alert's fallback text.
  const [lastAction, setLastAction] = useState<CardAction>('archive');
  // The site comes from research data: only an http(s) URL becomes a link.
  const website = safeHttpUrl(card.website);
  const emphasis = scoreEmphasis(sort);

  const runAction = async (action: CardAction) => {
    setLastAction(action);
    // `from` is the card's tab, so a click on a stale view is a 409 rather than
    // a move the admin did not ask for. Each action is only offered on its tab:
    // Save on New, Unsave on Saved, Archive on New or Saved, Restore on Archived.
    const result = await setStatus({
      id: card.id,
      status: ACTION_REQUEST[action].status,
      from: card.status,
    });
    if (!('error' in result)) onLeave?.(card, action);
  };

  const headerId = `radar-card-${card.id}-header`;
  const bodyId = `radar-card-${card.id}-body`;
  const toggle = () => setExpanded((open) => !open);

  // An MUI Accordion whose first child is a plain header rather than an
  // AccordionSummary: v7's summary renders a native <button>, and this header
  // holds links and buttons of its own (site, job board, Save…), which cannot nest
  // inside a button. So a mouse click anywhere on the header toggles the card
  // (every control in it stops its click), and the chevron in the status line
  // is the real, labelled toggle button for keyboard and screen readers.
  return (
    <Accordion
      variant="outlined"
      disableGutters
      expanded={expanded}
      slots={{ heading: 'div' }}
      slotProps={{ transition: { unmountOnExit: true } }}
      data-testid={`radar-card-${card.id}`}
      sx={{
        mb: 1.25,
        borderRadius: 2,
        // White card on the white page: the theme's paper is grey, which
        // reads as a disabled block here.
        bgcolor: 'background.default',
        '&:before': { display: 'none' },
        '&.Mui-expanded': { borderColor: 'text.disabled' },
      }}
    >
      <Box
        id={headerId}
        aria-controls={bodyId}
        onClick={toggle}
        sx={{ px: RESPONSIVE.launchRadar.cardPaddingX, pt: 1.5, pb: 1.25, cursor: 'pointer' }}
      >
        {/* sm+: name, one-liner and event in the left column, the scores in the
            right one beside all three. A phone has no room for that column:
            the name shares the top row with the scores and the one-liner and
            event run the full card width under both. The `1fr` second row
            takes the scores' extra height when the left column is shorter, so
            the name never gets a gap under it. */}
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1fr) auto',
            gridTemplateRows: 'auto 1fr',
            gridTemplateAreas: {
              xs: '"title scores" "body body"',
              sm: '"title scores" "body scores"',
            },
            columnGap: 1.5,
            width: '100%',
          }}
        >
          <Typography
            component="div"
            sx={{
              gridArea: 'title',
              minWidth: 0,
              alignSelf: { xs: 'center', sm: 'start' },
              fontWeight: 600,
              fontSize: 15,
              lineHeight: 1.3,
              // A long one-word name or domain breaks rather than overflow.
              overflowWrap: 'anywhere',
            }}
          >
            {card.company}
            {website ? (
              <Link
                href={website}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                color="text.secondary"
                sx={DOMAIN_SX}
              >
                {card.domain}
              </Link>
            ) : (
              <Box component="span" sx={{ ...DOMAIN_SX, color: 'text.secondary' }}>
                {card.domain}
              </Box>
            )}
          </Typography>
          <Box sx={{ gridArea: 'body', minWidth: 0, mt: RESPONSIVE.launchRadar.cardBodyMarginTop }}>
            {card.oneLiner && (
              <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.4 }}>
                {card.oneLiner}
              </Typography>
            )}
            <EventLine event={card.event} company={card.company} />
          </Box>
          <Box sx={{ gridArea: 'scores', display: 'flex', gap: 1.75, pt: 0.125 }}>
            <ScoreBadge label="Talent" value={card.scores.talent} emphasis={emphasis.talent} />
            <ScoreBadge label="VC" value={card.scores.vc} emphasis={emphasis.vc} />
          </Box>
          <CardStatusLine
            card={card}
            expanded={expanded}
            bodyId={bodyId}
            onToggle={toggle}
            // A card whose move succeeded is leaving this tab: keep its buttons
            // off until it is gone, so a second press cannot land on a stale
            // status (a 409). The cache drops it on success; this is the
            // belt to that brace.
            busy={isLoading || isSuccess}
            onAction={(action) => void runAction(action)}
            onDelete={() => onRequestDelete(card)}
          />
          {error && (
            <Alert
              severity="error"
              onClick={(e) => e.stopPropagation()}
              sx={{ gridColumn: '1 / -1', mt: 1, cursor: 'auto' }}
            >
              {extractErrorMessage(error, ACTION_REQUEST[lastAction].failed)}
            </Alert>
          )}
        </Box>
      </Box>
      {/* Same side padding as the header, so the body sits under the name. */}
      <AccordionDetails sx={{ pt: 0, pb: 1.5, px: RESPONSIVE.launchRadar.cardPaddingX }}>
        <CardBody card={card} />
      </AccordionDetails>
    </Accordion>
  );
}
