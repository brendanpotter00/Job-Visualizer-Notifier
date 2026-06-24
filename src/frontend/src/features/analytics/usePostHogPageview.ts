import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { usePostHog } from '@posthog/react';
import { POSTHOG_CONFIG } from '../../config/posthog';

export function usePostHogPageview(): void {
  const location = useLocation();
  const posthog = usePostHog();

  useEffect(() => {
    if (!POSTHOG_CONFIG.isEnabled || !posthog) return;
    posthog.capture('$pageview', { $current_url: window.location.href });
  }, [location.pathname, location.search, posthog]);
}
