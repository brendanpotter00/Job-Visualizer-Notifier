import { useGoogleOneTapLogin } from '@react-oauth/google';
import { AUTH_CONFIG } from '../../config/auth';
import { useAuth } from './useAuth';
import { useGoogleCredential } from './useGoogleCredential';
import { exchangeGoogleToken } from './exchangeGoogleToken';

export function GoogleOneTap() {
  const { isEnabled, isAuthenticated, isLoading } = useAuth();
  const { setGoogleCredential } = useGoogleCredential();

  useGoogleOneTapLogin({
    onSuccess: async (credentialResponse) => {
      if (!credentialResponse.credential) {
        console.warn('[GoogleOneTap] Success callback received no credential');
        return;
      }
      try {
        const auth0AccessToken = await exchangeGoogleToken(
          credentialResponse.credential,
          AUTH_CONFIG,
        );
        setGoogleCredential(auth0AccessToken);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        console.warn('[GoogleOneTap] Auth0 token exchange failed:', msg);
      }
    },
    onError: () => {
      console.warn('[GoogleOneTap] Login failed — user may have dismissed the prompt or cookies are blocked');
    },
    // Silently re-issue a credential for returning users on page load. Combined
    // with localStorage persistence in GoogleCredentialContext, this keeps
    // users logged in well beyond the ~1h Google ID token lifetime.
    auto_select: true,
    disabled: !isEnabled || !AUTH_CONFIG.googleClientId || isAuthenticated || isLoading,
  });

  return null;
}
