import type { ReactNode } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import type { LaunchRadarEvent } from '../../../features/admin/launchRadarTypes';
import { formatShortDate } from '../format';

/**
 * The event that put the company on the radar, in one line:
 * funding → "Series A **$35M**  Sep 17", launch → "Launch  Oct 6",
 * other → the headline, truncated.
 */
export function EventLine({ event }: { event: LaunchRadarEvent | null }) {
  if (!event) return null;
  const date = formatShortDate(event.announcedAt);
  let main: ReactNode;
  if (event.type === 'funding') {
    main = (
      <span>
        {event.round ?? 'Funding'}
        {event.amountUsd && (
          <>
            {' '}
            <Box component="b" sx={{ fontWeight: 600 }}>
              {event.amountUsd}
            </Box>
          </>
        )}
      </span>
    );
  } else if (event.type === 'launch') {
    main = <span>Launch</span>;
  } else {
    main = (
      <Box
        component="span"
        title={event.headline}
        sx={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {event.headline}
      </Box>
    );
  }
  return (
    <Typography
      component="div"
      variant="body2"
      data-testid="radar-event-line"
      sx={{ mt: 0.75, display: 'flex', gap: 1.25, minWidth: 0 }}
    >
      {main}
      {date && (
        <Box component="span" sx={{ color: 'text.disabled', flexShrink: 0 }}>
          {date}
        </Box>
      )}
    </Typography>
  );
}
