export interface User {
  id: string;
  auth0Id: string;
  email: string;
  displayName: string | null;
  givenName: string | null;
  familyName: string | null;
  pictureUrl: string | null;
  createdAt: string;
  updatedAt: string;
}

async function extractErrorDetail(response: Response): Promise<string | null> {
  return response
    .json()
    .then((b) => b.detail || b.message || b.error)
    .catch(() => null);
}

export async function fetchCurrentUser(token: string): Promise<User> {
  const response = await fetch('/api/users', {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
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
