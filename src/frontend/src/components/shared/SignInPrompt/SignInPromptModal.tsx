import { useId } from 'react';
import { Box, Dialog, DialogContent, IconButton } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { SignInPrompt, type SignInPromptMessageProps } from './SignInPrompt';

export interface SignInPromptModalProps extends SignInPromptMessageProps {
  open: boolean;
  onClose: () => void;
  /**
   * Optional override for the dialog's accessible name. When omitted, the
   * modal wires `aria-labelledby` to the rendered title `<Typography>` so
   * screen readers announce the actual heading (the prior `aria-label`-only
   * approach let the label drift from the visible title).
   */
  ariaLabel?: string;
}

/**
 * Modal presentation of the shared sign-in prompt. Delegates all rendering
 * and login wiring to `<SignInPrompt>`; this wrapper adds only the MUI
 * Dialog chrome (close button, backdrop, ESC handling).
 */
export function SignInPromptModal({
  open,
  onClose,
  title,
  subtitle,
  buttonText,
  ariaLabel,
}: SignInPromptModalProps) {
  // Generate a stable unique id for the title node so the Dialog paper can
  // reference it via `aria-labelledby`. Using `useId` keeps the id unique
  // across multiple concurrent modals on the same page.
  const generatedTitleId = useId();
  const titleId = `sign-in-prompt-title-${generatedTitleId}`;
  // `aria-labelledby` referencing the live title node is preferred over a
  // static `aria-label` because it cannot drift from the rendered heading.
  // If the caller insists on a distinct accessible name (e.g. screen-reader
  // verbosity tuning), `ariaLabel` overrides and we fall back to `aria-label`.
  const paperAria = ariaLabel
    ? { 'aria-label': ariaLabel }
    : { 'aria-labelledby': titleId };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="xs"
      fullWidth
      slotProps={{
        paper: paperAria,
      }}
    >
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', p: 1 }}>
        <IconButton
          aria-label="close"
          onClick={onClose}
          sx={{ color: 'text.secondary' }}
        >
          <CloseIcon />
        </IconButton>
      </Box>
      <DialogContent sx={{ pb: 4, px: { xs: 3, sm: 4 }, pt: 0, textAlign: 'center' }}>
        <SignInPrompt
          title={title}
          subtitle={subtitle}
          buttonText={buttonText}
          onRequestClose={onClose}
          titleId={titleId}
        />
      </DialogContent>
    </Dialog>
  );
}
