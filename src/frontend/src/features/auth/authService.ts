export interface User {
  id: string;
  /**
   * Provider subject: Auth0 `sub` or Google-prefixed One Tap `sub`.
   * Backend DB column is still named `auth0_id` for historical reasons;
   * this field tracks the most recent identity provider's subject.
   */
  providerSubject: string;
  email: string;
  displayName: string | null;
  givenName: string | null;
  familyName: string | null;
  pictureUrl: string | null;
  createdAt: string;
  updatedAt: string;
  isAdmin: boolean;
}

async function extractErrorDetail(response: Response): Promise<string | null> {
  return response
    .json()
    .then((b) => b.detail || b.message || b.error)
    .catch(() => null);
}

export async function fetchCurrentUser(
  token: string,
  signal?: AbortSignal
): Promise<User> {
  const response = await fetch('/api/users', {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
    signal,
  });

  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    throw new Error(detail || `Failed to fetch user (${response.status})`);
  }

  return response.json();
}

export async function updateCurrentUser(
  token: string,
  updates: { displayName: string | null }
): Promise<User> {
  const response = await fetch('/api/users', {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(updates),
  });

  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    throw new Error(detail || `Failed to update user (${response.status})`);
  }

  return response.json();
}

export async function fetchEnabledCompanies(
  token: string,
  signal?: AbortSignal
): Promise<string[]> {
  const response = await fetch('/api/users/enabled-companies', {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
    signal,
  });

  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    throw new Error(detail || `Failed to fetch enabled companies (${response.status})`);
  }

  const body = await response.json();
  return body.companyIds as string[];
}

export async function updateEnabledCompanies(
  token: string,
  companyIds: string[]
): Promise<string[]> {
  const response = await fetch('/api/users/enabled-companies', {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ companyIds }),
  });

  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    throw new Error(detail || `Failed to save enabled companies (${response.status})`);
  }

  const body = await response.json();
  return body.companyIds as string[];
}
