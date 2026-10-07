import { useState } from 'react';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import { useDeleteLaunchRadarCardMutation } from '../../../features/admin/adminApi';
import type { LaunchRadarCard } from '../../../features/admin/launchRadarTypes';
import { extractErrorMessage } from '../../../lib/errors';

interface DeleteCardDialogProps {
  /** The archived card to delete; `null` keeps the dialog closed. */
  card: Pick<LaunchRadarCard, 'id' | 'company' | 'domain'> | null;
  onClose: () => void;
}

/**
 * Confirm before the one irreversible action on the page. The backend keeps a
 * tombstone row (domain only) so the loop never posts this company again —
 * which is exactly what the body tells the admin.
 */
export function DeleteCardDialog({ card, onClose }: DeleteCardDialogProps) {
  const [deleteCard, { isLoading, error, reset }] = useDeleteLaunchRadarCardMutation();
  // Keep the last card on screen while the dialog's exit transition runs, so
  // the title does not blank out as it fades. (Adjusting state during render is
  // React's sanctioned "remember the previous value" pattern.)
  const [shown, setShown] = useState(card);
  if (card && card !== shown) {
    setShown(card);
  }

  const close = () => {
    if (isLoading) return;
    reset();
    onClose();
  };

  const confirm = async () => {
    if (!card) return;
    const result = await deleteCard({ id: card.id });
    // On failure the mutation's `error` renders the Alert below and the dialog
    // stays open so the admin can retry or cancel.
    if (!('error' in result)) {
      reset();
      onClose();
    }
  };

  return (
    <Dialog open={card !== null} onClose={close} aria-labelledby="delete-radar-card-title">
      {shown && (
        <>
          <DialogTitle id="delete-radar-card-title">
            Delete {shown.company} permanently?
          </DialogTitle>
          <DialogContent>
            <DialogContentText>
              The card and its research go away. The loop will not post {shown.domain} again.
            </DialogContentText>
            {error && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {extractErrorMessage(error, 'Failed to delete the card')}
              </Alert>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={close} disabled={isLoading} color="inherit">
              Cancel
            </Button>
            <Button onClick={confirm} disabled={isLoading} variant="contained" color="error">
              Delete
            </Button>
          </DialogActions>
        </>
      )}
    </Dialog>
  );
}
