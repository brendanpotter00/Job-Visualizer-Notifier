import { useGoogleOneTapLogin } from '@react-oauth/google';
import { AUTH_CONFIG } from '../../config/auth';
import { useAuth } from './useAuth';
import { useGoogleCredential } from './useGoogleCredential';

export function GoogleOneTap() {
  const { isEnabled, isAuthenticated } = useAuth();
  const { setGoogleCredential } = useGoogleCredential();

  useGoogleOneTapLogin({
    onSuccess: (credentialResponse) => {
      if (credentialResponse.credential) {
        setGoogleCredential(credentialResponse.credential);
      } else {
        console.warn('[GoogleOneTap] Success callback received no credential');
      }
    },
    onError: () => {
      console.warn('[GoogleOneTap] Login failed — user may have dismissed the prompt or cookies are blocked');
    },
    // Silently re-issue a credential for returning users on page load. Combined
    // with localStorage persistence in GoogleCredentialContext, this keeps
    // users logged in well beyond the ~1h Google ID token lifetime.
    auto_select: true,
    // Intentionally NOT gated on Auth0's `isLoading`: a Google-One-Tap-only user
    // has no Auth0 refresh token, so Auth0's silent-auth fallback
    // (/authorize?prompt=none) stalls ~30s behind blocked third-party cookies on
    // every stale load. Gating One Tap on that made the Google credential — and
    // therefore preference hydration — wait the full ~30s. One Tap auto_select
    // runs in parallel with Auth0 instead; useGoogleOneTapLogin already gates
    // internally on GSI script readiness, and `isAuthenticated` flips true the
    // instant the Google credential is set (even while Auth0 is still loading).
    disabled: !isEnabled || !AUTH_CONFIG.googleClientId || isAuthenticated,
  });

  return null;
}
