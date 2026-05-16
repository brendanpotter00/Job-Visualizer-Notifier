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

/**
 * Runtime guard for the ``/api/users`` response body.
 *
 * Symmetric to ``AdminUsersListResponse`` runtime validation in
 * ``adminApi.ts``. The backend hardening (``UserResponse.is_admin`` required,
 * no default) prevents Pydantic from emitting a body without ``isAdmin`` —
 * but a CDN error page or a future serializer regression could still land
 * a 2xx body that's missing the field. Without this guard, ``response.json()``
 * is cast to ``User`` and ``AdminRoute``'s ``!user.isAdmin`` check silently
 * demotes the admin (the exact "silently zero admins" failure mode the
 * companion adminApi guard prevents).
 *
 * Validates the minimum surface the rest of the app reads (``id``, ``email``,
 * ``isAdmin``). Strings and the boolean are checked by ``typeof`` so a
 * structurally-shaped error envelope (e.g. ``{ detail: '...' }``) is
 * rejected. Throws a descriptive ``Error`` that bubbles up through the
 * fetch promise.
 */
function parseUserResponse(raw: unknown): User {
  if (raw == null || typeof raw !== 'object') {
    throw new Error('Invalid /api/users response: body is not an object');
  }
  const obj = raw as Record<string, unknown>;
  if (typeof obj.id !== 'string' || obj.id.length === 0) {
    throw new Error('Invalid /api/users response: missing or non-string id');
  }
  if (typeof obj.email !== 'string' || obj.email.length === 0) {
    throw new Error('Invalid /api/users response: missing or non-string email');
  }
  if (typeof obj.isAdmin !== 'boolean') {
    // CRITICAL: a missing isAdmin field would otherwise be coerced to
    // ``undefined`` and ``!user.isAdmin`` would silently demote the admin
    // in AdminRoute. Surface as a hard failure instead.
    throw new Error('Invalid /api/users response: missing isAdmin field');
  }
  return obj as unknown as User;
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

  return parseUserResponse(await response.json());
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

  return parseUserResponse(await response.json());
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
