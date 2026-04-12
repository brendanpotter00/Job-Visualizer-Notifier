import { createContext, useContext, useState, type ReactNode } from 'react';

interface GoogleCredentialState {
  googleCredential: string | null;
  setGoogleCredential: (credential: string | null) => void;
}

const GoogleCredentialContext = createContext<GoogleCredentialState>({
  googleCredential: null,
  setGoogleCredential: () => {},
});

export function GoogleCredentialProvider({ children }: { children: ReactNode }) {
  const [googleCredential, setGoogleCredential] = useState<string | null>(null);
  return (
    <GoogleCredentialContext.Provider value={{ googleCredential, setGoogleCredential }}>
      {children}
    </GoogleCredentialContext.Provider>
  );
}

export function useGoogleCredential() {
  return useContext(GoogleCredentialContext);
}
