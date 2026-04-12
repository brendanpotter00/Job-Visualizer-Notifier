import { useContext } from 'react';
import { GoogleCredentialContext } from './GoogleCredentialContext';

export function useGoogleCredential() {
  return useContext(GoogleCredentialContext);
}
