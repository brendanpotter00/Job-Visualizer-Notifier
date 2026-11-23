import { useCallback, useEffect, useRef } from 'react';
import type { FocusEvent } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import IconButton from '@mui/material/IconButton';
import Link from '@mui/material/Link';
import Snackbar from '@mui/material/Snackbar';
import useMediaQuery from '@mui/material/useMediaQuery';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import { RESPONSIVE } from '../../config/responsive';
import { ROUTES } from '../../config/routes';

/** How long the toast stays up untouched, and after the pointer or focus leaves it (ms). */
export const SAVED_TOAST_AUTO_HIDE_MS = 6000;
export const SAVED_TOAST_RESUME_MS = 3000;

/** The check on the black toast: green that reads on black (well above 3:1). */
const TOAST_CHECK_COLOR = '#4cbb5e';

export interface OnboardingSavedToastProps {
  open: boolean;
  onClose: () => void;
}

/**
 * "Saved filters": shown once, after the questions close with answers saved.
 * Top right, just under the app bar. It links to the Saved Filters page, where
 * the answers can be changed later, and closes with ×.
 *
 * It hides after 6 seconds. Hovering it or focusing anything in it pauses the
 * timer; leaving starts a shorter 3-second one. The timer is ours rather than
 * Snackbar's `autoHideDuration`, which pauses on hover but not on focus.
 *
 * It has no role of its own: the gate's polite live region says "Saved as your
 * filters." once, so a screen reader does not also hear the toast as an alert.
 */
export function OnboardingSavedToast({ open, onClose }: OnboardingSavedToastProps) {
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hovered = useRef(false);
  const focused = useRef(false);
  // The latest onClose, read by the timer when it fires, so a parent that
  // passes a new function each render does not restart the countdown.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  const stop = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const start = useCallback(
    (ms: number) => {
      stop();
      timer.current = setTimeout(() => {
        timer.current = null;
        onCloseRef.current();
      }, ms);
    },
    [stop]
  );

  useEffect(() => {
    if (!open) return undefined;
    hovered.current = false;
    focused.current = false;
    start(SAVED_TOAST_AUTO_HIDE_MS);
    return stop;
  }, [open, start, stop]);

  const resumeIfIdle = () => {
    if (!hovered.current && !focused.current) start(SAVED_TOAST_RESUME_MS);
  };

  const handleBlur = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget as Node | null;
    if (next && event.currentTarget.contains(next)) return;
    focused.current = false;
    resumeIfIdle();
  };

  return (
    <Snackbar
      open={open}
      anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      // Our timer, not Snackbar's (see above). A click elsewhere on the page
      // does not dismiss it; Escape and × do.
      autoHideDuration={null}
      onClose={(_event, reason) => {
        if (reason === 'clickaway') return;
        onClose();
      }}
      transitionDuration={reducedMotion ? 0 : undefined}
      sx={{
        top: RESPONSIVE.onboarding.toastTop,
        right: RESPONSIVE.onboarding.toastRight,
      }}
    >
      <Box
        data-testid="onboarding-saved-toast"
        onMouseEnter={() => {
          hovered.current = true;
          stop();
        }}
        onMouseLeave={() => {
          hovered.current = false;
          resumeIfIdle();
        }}
        onFocus={() => {
          focused.current = true;
          stop();
        }}
        onBlur={handleBlur}
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 1,
          maxWidth: '100%',
          pl: '14px',
          pr: '4px',
          py: '2px',
          borderRadius: '8px',
          bgcolor: 'common.black',
          color: 'common.white',
          fontSize: '0.875rem',
          lineHeight: 1.45,
          boxShadow: 6,
        }}
      >
        <CheckIcon sx={{ color: TOAST_CHECK_COLOR, fontSize: 18, flex: 'none' }} />
        <Link
          component={RouterLink}
          to={ROUTES.SAVED_FILTERS}
          underline="always"
          onClick={onClose}
          sx={{
            minHeight: 40,
            display: 'inline-flex',
            alignItems: 'center',
            color: 'common.white',
            fontWeight: 500,
            textDecorationColor: 'currentColor',
            textUnderlineOffset: '3px',
            '&:focus-visible': { outline: '2px solid', outlineColor: 'common.white', outlineOffset: '2px' },
          }}
        >
          Saved filters
        </Link>
        <IconButton
          aria-label="Dismiss"
          onClick={onClose}
          sx={{
            color: 'common.white',
            borderRadius: '8px',
            '&:hover': { bgcolor: 'rgba(255,255,255,.14)' },
            '&:focus-visible': { outline: '2px solid', outlineColor: 'common.white' },
          }}
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>
    </Snackbar>
  );
}
