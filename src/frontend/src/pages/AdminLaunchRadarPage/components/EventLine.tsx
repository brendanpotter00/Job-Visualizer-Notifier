import type { ReactNode } from 'react';
import Box from '@mui/material/Box';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import type { LaunchRadarEvent } from '../../../features/admin/launchRadarTypes';
import { formatEventDate, hostnameOf, safeHttpUrl } from '../format';

/**
 * The line's pieces (the round and amount, the date, the link) each stay
 * whole and wrap as units on a narrow card, so a round never splits as
 * "Series / A $116 / million".
 */
const ITEM_SX = { whiteSpace: 'nowrap', flexShrink: 0 } as const;

/**
 * The first piece can be long (a headline, an unusual round name): wider
 * than the whole line, it ends in an ellipsis instead of overflowing the card.
 */
const MAIN_SX = {
  whiteSpace: 'nowrap',
  minWidth: 0,
  maxWidth: '100%',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
} as const;

/**
 * The event that put the company on the radar, in one line: funding →
 * "Series A **$35M**  Sep 17" ("Sep 2026" when only the month is known),
 * launch → "Launch  Oct 6", other → the headline, truncated. Then an
 * "Announcement" link to the news post or press release behind it, when that
 * is an `http(s)` URL. The link's accessible name carries the company
 * ("Announcement Lightfield"), so a page of cards has no two links with the
 * same name.
 */
export function EventLine({ event, company }: { event: LaunchRadarEvent | null; company: string }) {
  if (!event) return null;
  const date = formatEventDate(event.announcedAt);
  const sourceUrl = safeHttpUrl(event.sourceUrl);
  let main: ReactNode;
  if (event.type === 'funding') {
    main = (
      <Box component="span" sx={MAIN_SX}>
        {event.round ?? 'Funding'}
        {event.amountUsd && (
          <>
            {' '}
            <Box component="b" sx={{ fontWeight: 600 }}>
              {event.amountUsd}
            </Box>
          </>
        )}
      </Box>
    );
  } else if (event.type === 'launch') {
    main = (
      <Box component="span" sx={MAIN_SX}>
        Launch
      </Box>
    );
  } else {
    main = (
      <Box component="span" title={event.headline} sx={MAIN_SX}>
        {event.headline}
      </Box>
    );
  }
  return (
    <Typography
      component="div"
      variant="body2"
      data-testid="radar-event-line"
      sx={{
        mt: 0.75,
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'baseline',
        columnGap: 1.25,
        rowGap: 0.25,
        minWidth: 0,
      }}
    >
      {main}
      {date && (
        <Box component="span" sx={{ ...ITEM_SX, color: 'text.disabled' }}>
          {date}
        </Box>
      )}
      {sourceUrl && (
        // The card header toggles on a click, so the link stops it: it opens
        // the announcement and leaves the card as it was.
        <Link
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          title={hostnameOf(sourceUrl) ?? undefined}
          aria-label={`Announcement ${company}`}
          onClick={(e) => e.stopPropagation()}
          color="text.secondary"
          sx={{ ...ITEM_SX, fontSize: 12 }}
        >
          Announcement
        </Link>
      )}
    </Typography>
  );
}
