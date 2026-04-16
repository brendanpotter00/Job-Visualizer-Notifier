import { useGoogleOneTapLogin } from '@react-oauth/google';
import { AUTH_CONFIG } from '../../config/auth';
import { useAuth } from './useAuth';
import { useGoogleCredential } from './useGoogleCredential';

export function GoogleOneTap() {
  const { isEnabled, isAuthenticated, isLoading } = useAuth();
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
    disabled: !isEnabled || !AUTH_CONFIG.googleClientId || isAuthenticated || isLoading,
  });

  return null;
}
