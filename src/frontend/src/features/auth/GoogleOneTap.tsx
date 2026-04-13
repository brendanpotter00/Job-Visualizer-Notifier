import { useGoogleOneTapLogin } from '@react-oauth/google';
import { useAuth } from './useAuth';

export function GoogleOneTap() {
  const { isEnabled, isAuthenticated, isLoading, setGoogleCredential } = useAuth();

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
    disabled: !isEnabled || isAuthenticated || isLoading,
  });

  return null;
}
