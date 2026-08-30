import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';

interface TrackAnywayActionProps {
  onClick: () => void;
}

/**
 * The way out from a GUESSED "we already publish this" notice: tell us it is not the
 * same company, and add it anyway.
 *
 * IT EXISTS FOR EXACTLY ONE CALLER NOW, and the reason is the difference between the
 * two things that notice can mean:
 *
 *  - We matched a BOARD — a resolved `(ats, boardToken)` pair, or a careers host in our
 *    own declared table. That is an exact identifier. A private duplicate of a board we
 *    already publish re-scrapes the same feed and hands the user a chart whose history
 *    starts today instead of the full history one click away, so it is strictly worse
 *    for them. Offering it was a trap, and that branch is now terminal with no button.
 *  - We matched a NAME inside the domain (`lifeatspotify.com` → Spotify). That is a
 *    guess, and its failure mode is a false positive: somebody whose company merely
 *    shares a string with one of ours. With no way out, a wrong guess HARD-BLOCKS them
 *    from adding a legitimately different company, with no way to tell us we are wrong.
 *    That is a worse anti-pattern than the one we removed, so this branch keeps a way
 *    out — this component.
 *
 * WHICH IS WHY THE COPY IS WHAT IT IS. "Track it separately anyway" invited a duplicate;
 * "This isn't the same company" corrects a wrong guess. The caption names the consequence
 * of being right about that rather than the cost of a duplicate, because on this branch
 * the user is not choosing a duplicate — they are telling us we misread their URL.
 *
 * DELIBERATELY SECONDARY still. A plain text button, never `variant="contained"`, under
 * the notice's link rather than beside it: the link is the answer for most people who see
 * this, and this is the minority correction.
 *
 * It owns no mutation. `DiscoveryStatus` renders it and its parent holds the mutation;
 * giving this a third would mean a click here resolving into state neither of them
 * renders.
 *
 * NO IN-FLIGHT STATE, and it used to have one. Clicking this fires the page's add
 * mutation, which clears its own `data` — so the notice this button lives inside
 * unmounts on the very next render and the page's spinner takes the screen. A
 * `disabled` + "Adding…" label had nothing left to render itself into. The window a
 * double-click could squeeze into is closed on the page, where the mutation is.
 */
export function TrackAnywayAction({ onClick }: TrackAnywayActionProps) {
  return (
    <Box sx={{ mt: 1 }}>
      <Button size="small" onClick={onClick} data-testid="track-anyway-button">
        This isn&apos;t the same company
      </Button>
      <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
        We matched the name in the web address. If we got that wrong, we&apos;ll set this
        board up as its own company.
      </Typography>
    </Box>
  );
}
