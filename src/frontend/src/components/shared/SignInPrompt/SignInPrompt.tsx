import { Box, Button, Stack, Typography } from '@mui/material';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import { useAuth } from '../../../features/auth/useAuth';

export interface SignInPromptMessageProps {
  title: string;
  subtitle: string;
  buttonText: string;
}

export interface SignInPromptProps extends SignInPromptMessageProps {
  /**
   * Invoked after the CTA dispatches `login()`. Modal variants pass
   * `onClose` here so the modal dismisses itself after the user clicks
   * the CTA.
   */
  onRequestClose?: () => void;
  /**
   * Optional DOM id assigned to the title `Typography`. Modal variants pass
   * this through so they can wire `aria-labelledby` on the Dialog paper for
   * screen-reader title announcements.
   */
  titleId?: string;
}

/**
 * Shared sign-in core: lock icon + headline + subtitle + CTA button wired to
 * `useAuth().login()`. Returns `null` when `!isEnabled || isLoading ||
 * isAuthenticated` — matches SignInOverlay's existing conditional-render
 * semantics so consumers do not need to gate it themselves.
 */
export function SignInPrompt({
  title,
  subtitle,
  buttonText,
  onRequestClose,
  titleId,
}: SignInPromptProps) {
  const { isAuthenticated, isEnabled, isLoading, login } = useAuth();

  if (!isEnabled || isLoading || isAuthenticated) {
    return null;
  }

  const handleSignIn = () => {
    void login().catch((error) => {
      console.error('[SignInPrompt] Login failed:', error);
    });
    onRequestClose?.();
  };

  return (
    <Stack spacing={2} alignItems="center">
      <LockOutlinedIcon
        aria-hidden="true"
        sx={{ fontSize: 32, color: 'text.secondary' }}
      />
      <Box>
        <Typography id={titleId} variant="h6" component="p" gutterBottom>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {subtitle}
        </Typography>
      </Box>
      <Button variant="contained" size="large" onClick={handleSignIn}>
        {buttonText}
      </Button>
    </Stack>
  );
}
