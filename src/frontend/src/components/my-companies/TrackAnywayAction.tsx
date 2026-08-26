import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Typography from '@mui/material/Typography';

interface TrackAnywayActionProps {
  onClick: () => void;
  /** Disables the button and swaps its label while the add is in flight. */
  isLoading?: boolean;
}

/**
 * The escape hatch under an "we already track this" notice: track a private copy anyway.
 *
 * DELIBERATELY SECONDARY. A plain text button, never `variant="contained"`, sitting under
 * the notice's link rather than beside it — the primary action is the link to the page
 * that already has the answer, and this is the minority choice. The caption is not
 * decoration either: it names the cost ("its history starts today"), which is the whole
 * difference between an informed choice and a reflex.
 *
 * It must keep existing. Some people legitimately want their own copy of a board we
 * publish — a different filter set, a private annotation, a clean start — and "we already
 * track this" is a suggestion, not a refusal. That is also why the notice above it is a
 * `200` rather than an error.
 *
 * ONE component for both places the notice appears, so the copy cannot drift between
 * them. `AddCompanyCTA` renders it after an ATS board matched a published `(ats,
 * board_token)`; `DiscoveryStatus` renders it after a careers URL matched a published
 * script board's host. Those are two different backend checks and the same user choice,
 * and a second copy of this markup is how the two answers start reading differently.
 *
 * It owns no mutation. Both callers already hold one (`AddCompanyCTA` its own,
 * `DiscoveryStatus` its parent's), and giving this a third would mean a click here
 * resolving into state neither of them renders.
 */
export function TrackAnywayAction({ onClick, isLoading = false }: TrackAnywayActionProps) {
  return (
    <Box sx={{ mt: 1 }}>
      <Button
        size="small"
        onClick={onClick}
        disabled={isLoading}
        data-testid="track-anyway-button"
      >
        {isLoading ? 'Adding…' : 'Track it separately anyway'}
      </Button>
      <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
        Adds a private copy of the same board. Its history starts today.
      </Typography>
    </Box>
  );
}
