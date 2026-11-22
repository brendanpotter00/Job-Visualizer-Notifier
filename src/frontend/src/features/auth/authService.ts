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

/**
 * Pull a human-readable error string out of a JSON error body.
 *
 * Filters by ``typeof === 'string'`` at every step so a structurally-shaped
 * payload (e.g. ``{ error: { code: 'BACKEND_DOWN', message: 'pool exhausted' } }``)
 * doesn't get coerced to ``"[object Object]"`` when ``new Error(value)`` is
 * called on the result. When the top-level ``error`` field is itself an
 * object with a ``message`` string, surface that — the upstream still loses
 * the structured code, but at least the admin reads a real sentence instead
 * of ``[object Object]``.
 */
async function extractErrorDetail(response: Response): Promise<string | null> {
  return response
    .json()
    .then((b: unknown) => {
      if (b == null || typeof b !== 'object') return null;
      const obj = b as Record<string, unknown>;
      if (typeof obj.detail === 'string' && obj.detail.length > 0) {
        return obj.detail;
      }
      if (typeof obj.message === 'string' && obj.message.length > 0) {
        return obj.message;
      }
      if (typeof obj.error === 'string' && obj.error.length > 0) {
        return obj.error;
      }
      if (obj.error != null && typeof obj.error === 'object') {
        const nested = (obj.error as Record<string, unknown>).message;
        if (typeof nested === 'string' && nested.length > 0) {
          return nested;
        }
      }
      return null;
    })
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

export async function fetchCurrentUser(token: string, signal?: AbortSignal): Promise<User> {
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

/**
 * Record one full-page-load visit for the authenticated user.
 *
 * Fire-and-forget telemetry called once per full page load / refresh by
 * ``useRecordVisit`` — it backs the admin roster's "most frequent users"
 * view. The backend increments ``visit_count`` and returns 204 with no body.
 * Throws on a non-2xx so the caller can log-and-swallow (a failed visit count
 * must never break the app).
 */
export async function recordVisit(token: string, sessionId?: string): Promise<void> {
  // The body is optional server-side; send one only when there is a session id
  // so a build without PostHog makes exactly the request it always made.
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/json',
  };
  const init: RequestInit = { method: 'POST', headers };
  if (sessionId) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify({ sessionId });
  }
  const response = await fetch('/api/users/visit', init);

  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    throw new Error(detail || `Failed to record visit (${response.status})`);
  }
}

/** Where a job card was rendered. Mirrors `ApplyClickSurface` in the backend `models.py`. */
export type ApplyClickSurface = 'recent' | 'company' | 'company_bucket' | 'my_company' | 'landing';

export interface ApplyClickPayload {
  sourceId: string;
  jobId: string;
  surface: ApplyClickSurface;
  sessionId?: string;
}

/**
 * Log one press of a job card's Apply button (signed-in users only).
 *
 * `keepalive` lets the request finish even if the page goes away, so the caller
 * never has to wait for it: the job opens in its new tab at once. The backend
 * computes the job's age itself. Throws on a non-2xx so the caller can
 * log-and-swallow, like `recordVisit`.
 */
export async function recordApplyClick(token: string, payload: ApplyClickPayload): Promise<void> {
  const response = await fetch('/api/users/apply-click', {
    method: 'POST',
    keepalive: true,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Failed to record apply click (${response.status})`);
  }
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

export interface EnabledCompaniesResult {
  companyIds: string[];
  // When true, companies added after the user's last save auto-enroll into
  // their feed. Defaults to true if the backend omits it (older payloads).
  autoEnroll: boolean;
}

export async function fetchEnabledCompanies(
  token: string,
  signal?: AbortSignal
): Promise<EnabledCompaniesResult> {
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
  return {
    companyIds: body.companyIds as string[],
    autoEnroll: (body.autoEnrollNewCompanies ?? true) as boolean,
  };
}

export async function updateEnabledCompanies(
  token: string,
  companyIds: string[],
  autoEnroll: boolean
): Promise<EnabledCompaniesResult> {
  const response = await fetch('/api/users/enabled-companies', {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ companyIds, autoEnrollNewCompanies: autoEnroll }),
  });

  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    throw new Error(detail || `Failed to save enabled companies (${response.status})`);
  }

  const body = await response.json();
  return {
    companyIds: body.companyIds as string[],
    autoEnroll: (body.autoEnrollNewCompanies ?? true) as boolean,
  };
}
