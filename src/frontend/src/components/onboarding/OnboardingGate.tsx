import { useCallback, useState } from 'react';
import { useLocation } from 'react-router-dom';
import Box from '@mui/material/Box';
import { AUTH_CONFIG } from '../../config/auth';
import { useAuth } from '../../features/auth/useAuth';
import { useCurrentUser } from '../../features/auth/useCurrentUser';
import type { OnboardingResult } from '../../features/savedFilters/savedFiltersApi';
import { VISUALLY_HIDDEN_SX } from '../../lib/visuallyHidden';
import { OnboardingFlow } from './OnboardingFlow';
import { OnboardingSavedToast } from './OnboardingSavedToast';
import {
  SAVED_FILTERS_ANNOUNCEMENT,
  isOnboardingExcludedPath,
  savedFiltersHaveAnswers,
} from './onboardingModel';

/**
 * Opens the first-sign-in questions for an account that has not answered them.
 *
 * Mounted once, in `RootLayout`, so it covers every sign-in path (Auth0 and
 * Google One-Tap alike): it reads the SERVER's stamp, not a sign-in event.
 * The questions open ONLY when the signed-in user's `onboardingCompletedAt`
 * is exactly `null`. `undefined` (a backend older than the field, or a user
 * still loading) never opens them, and neither does a timestamp, so a later
 * sign-in goes straight to the list. Never on `/` or `/pricing`.
 *
 * When the answers are saved the dialog fades out; then the user's stamp is
 * set locally (no refetch) and, if any answer was given, the "Saved filters"
 * toast shows and the live region says "Saved as your filters." once. The
 * announcement waits for the fade so it is not spoken from under the dialog,
 * which hides the rest of the page from screen readers while it is open.
 *
 * A Skip that fails to save closes the questions for this visit only; the
 * stamp stays `null`, so they open again on the next page load.
 */
export function OnboardingGate() {
  const { isAuthenticated } = useAuth();
  const { user, setUser } = useCurrentUser();
  const { pathname } = useLocation();
  const [saved, setSaved] = useState<OnboardingResult | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [toastOpen, setToastOpen] = useState(false);
  const [announcement, setAnnouncement] = useState('');

  const eligible =
    isAuthenticated &&
    !AUTH_CONFIG.bypassEnabled &&
    user?.onboardingCompletedAt === null &&
    !isOnboardingExcludedPath(pathname);

  const handleExited = () => {
    if (!saved) return;
    setUser((current) =>
      current ? { ...current, onboardingCompletedAt: saved.onboardingCompletedAt } : current
    );
    if (savedFiltersHaveAnswers(saved.savedFilters)) {
      setToastOpen(true);
      setAnnouncement(SAVED_FILTERS_ANNOUNCEMENT);
    }
    setSaved(null);
  };

  const closeToast = useCallback(() => setToastOpen(false), []);

  return (
    <>
      {eligible && (
        <OnboardingFlow
          open={saved === null && !dismissed}
          onDone={setSaved}
          onDismiss={() => setDismissed(true)}
          onExited={handleExited}
        />
      )}
      <OnboardingSavedToast open={toastOpen} onClose={closeToast} />
      <Box aria-live="polite" sx={VISUALLY_HIDDEN_SX}>
        {announcement}
      </Box>
    </>
  );
}
