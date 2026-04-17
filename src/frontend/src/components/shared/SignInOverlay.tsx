import { Box, Button, Stack, Typography } from '@mui/material';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import { useAuth } from '../../features/auth/useAuth';
import { SIGN_IN_OVERLAY_MESSAGES } from '../../constants/messages';
import { SIGN_IN_OVERLAY_CONFIG } from '../../constants/ui';

/**
 * Theme palette backgrounds supported by the overlay.
 * - 'default' -> `theme.palette.background.default` (#ffffff)
 * - 'paper'   -> `theme.palette.background.paper`   (#f5f5f5)
 */
export type SignInOverlayBackground = 'default' | 'paper';

interface SignInOverlayProps {
  /**
   * Height of the gradient fade zone in pixels.
   * Controls how tall the transparent-to-solid transition is.
   * @default SIGN_IN_OVERLAY_CONFIG.GRADIENT_HEIGHT (120)
   */
  gradientHeight?: number;

  /**
   * Which theme background color the gradient fades to.
   * Use `'default'` when the overlay sits on the page background and
   * `'paper'` when it sits inside a `<Paper>` container.
   * @default 'default'
   */
  background?: SignInOverlayBackground;
}

/**
 * Overlay shown at the bottom of job lists when the user is signed out.
 *
 * Renders a gradient fade followed by a sign-in CTA to encourage sign-up.
 * The parent container must set `position: relative` so this component
 * anchors to its bottom edge.
 *
 * Returns `null` when the user is authenticated, auth is disabled, or auth
 * is still loading (avoids a brief flash during initial Auth0 bootstrap).
 *
 * @example
 * ```tsx
 * <Box sx={{ position: 'relative', overflow: 'hidden' }}>
 *   <JobList jobs={limitedJobs} />
 *   <SignInOverlay />
 * </Box>
 * ```
 */
export function SignInOverlay({
  gradientHeight = SIGN_IN_OVERLAY_CONFIG.GRADIENT_HEIGHT,
  background = 'default',
}: SignInOverlayProps = {}) {
  const { isAuthenticated, isEnabled, isLoading, login } = useAuth();

  if (!isEnabled || isLoading || isAuthenticated) {
    return null;
  }

  const handleSignIn = () => {
    // Surface login errors to the console; users can retry via the button.
    // UserMenu follows the same error path for the top-bar sign-in.
    void login().catch((error) => {
      console.error('[SignInOverlay] Login failed:', error);
    });
  };

  return (
    <Box
      sx={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 2,
        pointerEvents: 'none',
      }}
    >
      <Box
        aria-hidden="true"
        sx={{
          height: gradientHeight,
          background: (theme) =>
            `linear-gradient(to bottom, rgba(0,0,0,0) 0%, ${theme.palette.background[background]} 100%)`,
        }}
      />
      <Box
        role="region"
        aria-label={SIGN_IN_OVERLAY_MESSAGES.ARIA_LABEL}
        sx={{
          bgcolor: `background.${background}`,
          textAlign: 'center',
          px: { xs: 2, sm: 3 },
          py: { xs: 3, sm: 4 },
          pointerEvents: 'auto',
        }}
      >
        <Stack spacing={2} alignItems="center">
          <LockOutlinedIcon
            aria-hidden="true"
            sx={{ fontSize: 32, color: 'text.secondary' }}
          />
          <Box>
            <Typography variant="h6" component="p" gutterBottom>
              {SIGN_IN_OVERLAY_MESSAGES.TITLE}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {SIGN_IN_OVERLAY_MESSAGES.SUBTITLE}
            </Typography>
          </Box>
          <Button variant="contained" size="large" onClick={handleSignIn}>
            {SIGN_IN_OVERLAY_MESSAGES.BUTTON_TEXT}
          </Button>
        </Stack>
      </Box>
    </Box>
  );
}
