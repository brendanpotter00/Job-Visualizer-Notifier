import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Typography from '@mui/material/Typography';
import { OpenInNew } from '@mui/icons-material';
import type { EnrichmentNeedsHumanRow } from '../../../features/admin/adminApi';

interface JobDescriptionDialogProps {
  open: boolean;
  row: EnrichmentNeedsHumanRow | null;
  onClose: () => void;
}

/**
 * Read-only viewer for one needs-human row's FULL cleaned description (the
 * CorrectionDialog analog — same Dialog idiom, prop shape, and close handling).
 * The expand row only shows a 4-line clamp; this un-clamps it, preserves the
 * source line breaks (`whiteSpace: 'pre-wrap'`), and scrolls for long postings
 * (`scroll="paper"` + `dividers`). The header carries the title + company, and
 * a prominent "Open job posting" action lets the admin jump to the live posting.
 *
 * Nulls are handled here so the dialog is safe for any row: an empty/absent
 * description shows a muted fallback, and an absent `url` drops the external
 * action entirely (the caller renders such a title as plain text too).
 */
export function JobDescriptionDialog({ open, row, onClose }: JobDescriptionDialogProps) {
  if (!row) return null;

  const description = row.cleanDescription?.trim();

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth scroll="paper">
      <DialogTitle>
        {row.title ?? row.jobListingId}
        {row.company && (
          <Typography variant="body2" color="text.secondary">
            {row.company}
          </Typography>
        )}
      </DialogTitle>
      <DialogContent dividers>
        {description ? (
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
            {description}
          </Typography>
        ) : (
          <Typography variant="body2" color="text.secondary">
            No description available.
          </Typography>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        {row.url && (
          <Button
            variant="contained"
            component="a"
            href={row.url}
            target="_blank"
            rel="noopener noreferrer"
            endIcon={<OpenInNew />}
          >
            Open job posting
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
