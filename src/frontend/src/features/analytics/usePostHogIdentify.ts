import { useEffect } from 'react';
import { usePostHog } from '@posthog/react';
import { POSTHOG_CONFIG } from '../../config/posthog';
import { useCurrentUser } from '../auth/useCurrentUser';

export function usePostHogIdentify(): void {
  const posthog = usePostHog();
  const { user } = useCurrentUser();

  useEffect(() => {
    if (!POSTHOG_CONFIG.isEnabled || !posthog) return;

    if (user) {
      posthog.identify(user.providerSubject, {
        email: user.email,
        name: user.displayName ?? undefined,
        isAdmin: user.isAdmin,
      });
    } else {
      posthog.reset();
    }
  }, [user, posthog]);
}
