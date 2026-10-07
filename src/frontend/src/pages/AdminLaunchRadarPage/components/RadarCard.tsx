import { useState } from 'react';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import { useSetLaunchRadarCardStatusMutation } from '../../../features/admin/adminApi';
import type { LaunchRadarCard } from '../../../features/admin/launchRadarTypes';
import { extractErrorMessage } from '../../../lib/errors';
import { CardBody } from './CardBody';
import { CardStatusLine } from './CardStatusLine';
import { EventLine } from './EventLine';
import { ScoreBadge } from './ScoreBadge';

/**
 * The body is indented to sit under the company name (32px logo + 12px gap +
 * the summary's 14px padding = 58px). Phones drop the indent, so the lists get
 * the full ~360px width; `sm` restates the desktop value.
 */
const BODY_INDENT = { xs: 1.75, sm: 7.25 } as const;

interface RadarCardProps {
  card: LaunchRadarCard;
  /** Opens the page's single confirm dialog; deleting is never one click. */
  onRequestDelete: (card: LaunchRadarCard) => void;
}

/**
 * One company the loop found. Closed: logo letter, name + site, one-liner, the
 * event, Talent and VC scores, and one status line with the lifecycle actions.
 * Open: `CardBody`.
 */
export function RadarCard({ card, onRequestDelete }: RadarCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [setStatus, { isLoading, error }] = useSetLaunchRadarCardStatusMutation();
  const letter = card.company.trim().charAt(0).toUpperCase() || '?';

  const headerId = `radar-card-${card.id}-header`;
  const bodyId = `radar-card-${card.id}-body`;
  const toggle = () => setExpanded((open) => !open);

  // An MUI Accordion whose first child is a plain header rather than an
  // AccordionSummary: v7's summary renders a native <button>, and this header
  // holds links and buttons of its own (site, PR, Archive…), which cannot nest
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
        // White card on the white page, as in the plan's mock (the theme's
        // paper is grey, which reads as a disabled block here).
        bgcolor: 'background.default',
        '&:before': { display: 'none' },
        '&.Mui-expanded': { borderColor: 'text.disabled' },
      }}
    >
      <Box
        id={headerId}
        aria-controls={bodyId}
        onClick={toggle}
        sx={{ px: 1.75, pt: 1.5, pb: 1.25, cursor: 'pointer' }}
      >
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: '32px minmax(0, 1fr) auto',
            columnGap: 1.5,
            width: '100%',
          }}
        >
          <Box
            aria-hidden
            sx={{
              width: 32,
              height: 32,
              borderRadius: 1.5,
              bgcolor: 'common.black',
              color: 'common.white',
              display: 'grid',
              placeItems: 'center',
              fontWeight: 700,
              fontSize: 14,
            }}
          >
            {letter}
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography component="div" sx={{ fontWeight: 600, fontSize: 15, lineHeight: 1.3 }}>
              {card.company}
              <Link
                href={card.website}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                color="text.secondary"
                sx={{ fontSize: 12, fontWeight: 400, ml: 1 }}
              >
                {card.domain}
              </Link>
            </Typography>
            {card.oneLiner && (
              <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.4 }}>
                {card.oneLiner}
              </Typography>
            )}
            <EventLine event={card.event} />
          </Box>
          <Box sx={{ display: 'flex', gap: 1.75, pt: 0.125 }}>
            <ScoreBadge label="Talent" value={card.scores.talent} />
            <ScoreBadge label="VC" value={card.scores.vc} />
          </Box>
          <CardStatusLine
            card={card}
            expanded={expanded}
            bodyId={bodyId}
            onToggle={toggle}
            busy={isLoading}
            onArchive={() => setStatus({ id: card.id, status: 'archived' })}
            onRestore={() => setStatus({ id: card.id, status: 'new' })}
            onDelete={() => onRequestDelete(card)}
          />
          {error && (
            <Alert
              severity="error"
              onClick={(e) => e.stopPropagation()}
              sx={{ gridColumn: '2 / -1', mt: 1, cursor: 'auto' }}
            >
              {extractErrorMessage(
                error,
                card.status === 'new' ? 'Failed to archive the card' : 'Failed to restore the card'
              )}
            </Alert>
          )}
        </Box>
      </Box>
      <AccordionDetails sx={{ pt: 0, pb: 1.5, pr: 1.75, pl: BODY_INDENT }}>
        <CardBody card={card} />
      </AccordionDetails>
    </Accordion>
  );
}
