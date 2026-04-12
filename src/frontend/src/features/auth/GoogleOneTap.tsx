import { useGoogleOneTapLogin } from '@react-oauth/google';
import { useAuth } from './useAuth';

export function GoogleOneTap() {
  const { isEnabled, isAuthenticated, isLoading, setGoogleCredential } = useAuth();

  useGoogleOneTapLogin({
    onSuccess: (credentialResponse) => {
      if (credentialResponse.credential) {
        setGoogleCredential(credentialResponse.credential);
      }
    },
    onError: () => {
      console.warn('Google One Tap failed');
    },
    disabled: !isEnabled || isAuthenticated || isLoading,
  });

  return null;
}
