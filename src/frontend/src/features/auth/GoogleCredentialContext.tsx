import { createContext, useState, type ReactNode } from 'react';

export interface GoogleCredentialState {
  googleCredential: string | null;
  setGoogleCredential: (credential: string | null) => void;
}

// eslint-disable-next-line react-refresh/only-export-components
export const GoogleCredentialContext = createContext<GoogleCredentialState>({
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
