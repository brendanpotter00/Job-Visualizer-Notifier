import { Box, Dialog, DialogContent, IconButton } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { SignInPrompt, type SignInPromptMessageProps } from './SignInPrompt';

export interface SignInPromptModalProps extends SignInPromptMessageProps {
  open: boolean;
  onClose: () => void;
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
  const resolvedAriaLabel = ariaLabel ?? title;
  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="xs"
      fullWidth
      slotProps={{
        paper: {
          'aria-label': resolvedAriaLabel,
        },
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
        />
      </DialogContent>
    </Dialog>
  );
}
