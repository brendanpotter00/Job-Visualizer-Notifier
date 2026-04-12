# Auth0 Authentication Integration Plan

## Context

Add user authentication to the Job Posting Analytics app using Auth0 as the auth provider. The app has a React frontend (Vite + Redux + MUI) deployed on Vercel and a Python FastAPI backend deployed on Railway with PostgreSQL. Auth is **optional** -- the app continues to work without login, but authenticated users will gain access to an Account page and (in the future) saved filters and saved companies.

**Architecture:**
- **Frontend** (`@auth0/auth0-react`): Handles the full OAuth flow (login, callback, token exchange) via Auth0's Universal Login page. Google social login is configured in the Auth0 dashboard -- no code changes needed for specific providers.
- **Backend** (`PyJWT[crypto]`): Validates JWT access tokens from Auth0 against the JWKS endpoint. Does NOT use the Auth0 Python SDK (`authlib` or `python-jose`) -- those are designed for server-rendered apps where the backend handles the full OAuth flow, not SPA+API architectures.
- **Database**: New `users_{env}` table with Auth0 ID as external identity link.

**Why not the Auth0 Python SDK?** The Auth0 Python SDK handles login/callback/logout endpoints and Management API calls -- but our React frontend already does the OAuth flow. The backend only needs to validate Bearer tokens, which is a standard JWT operation. Using PyJWT is simpler, has no session management overhead, and follows the standard SPA+API pattern.

**Auth0 access token claims:** By default, Auth0 access tokens for custom APIs only contain `sub`, `iss`, `aud`, and scopes -- NOT profile claims like `email`, `given_name`, `family_name`, or `picture`. An **Auth0 Action** (Post Login trigger) is required to add these claims so the backend can read them from the JWT during user upsert.

---

## Work Units

### Unit 1: Backend -- Complete Auth Stack (DONE)

**Files created:**
- `src/backend/api/auth/__init__.py` -- Package init
- `src/backend/api/auth/jwt.py` -- JWKS-based JWT validation using `PyJWKClient`
- `src/backend/api/auth/dependencies.py` -- `get_current_user` (required) and `get_optional_user` (optional) FastAPI dependencies using `HTTPBearer`
- `src/backend/api/services/user_service.py` -- `get_or_create_user()` (upsert via `ON CONFLICT`), `get_user_by_auth0_id()`, `update_user()`
- `src/backend/api/routers/users.py` -- `GET /api/users` (get-or-create current user), `PUT /api/users` (update profile)
- `src/backend/api/tests/test_users_router.py` -- Tests for user endpoints (mock auth dependency)
- `src/backend/api/tests/test_auth.py` -- Tests for JWT validation (generate test RSA keys)

**Files modified:**
- `scripts/shared/database.py` -- Add `users_{env}` table to `init_schema()`, add `"users"` mapping to `_get_table_name()`
- `src/backend/api/config.py` -- Add `auth0_domain`, `auth0_audience` settings
- `src/backend/api/models.py` -- Add `UserResponse` and `UserUpdateRequest` Pydantic models (with camelCase alias pattern). `display_name` must have `Field(max_length=100)`. `picture_url` is NOT included in `UserUpdateRequest` -- it is read-only, populated only from Auth0 JWT claims during upsert.
- `src/backend/api/main.py` -- Register users router: `app.include_router(users.router, prefix="/api/users", tags=["users"])`
- `src/backend/api/requirements.txt` -- Add `PyJWT[crypto]>=2.8.0` (import `jwt.exceptions.ExpiredSignatureError`, `jwt.exceptions.InvalidTokenError`, `jwt.PyJWKClientError` for specific error handling)
- `src/backend/api/tests/conftest.py` -- Add users table cleanup, `_make_user`/`_insert_user` helpers, mock auth dependency fixture

**Database schema for `users_{env}`:**
```sql
CREATE TABLE IF NOT EXISTS users_{env} (
    id TEXT PRIMARY KEY,              -- UUID string (generated in Python)
    auth0_id TEXT NOT NULL UNIQUE,    -- Auth0 'sub' claim (e.g., "auth0|abc123" or "google-oauth2|abc123")
    email TEXT NOT NULL,
    display_name TEXT,
    given_name TEXT,
    family_name TEXT,
    picture_url TEXT,
    created_at TEXT NOT NULL,         -- ISO timestamp (matches existing convention)
    updated_at TEXT NOT NULL          -- ISO timestamp
);
CREATE INDEX IF NOT EXISTS idx_users_{env}_auth0_id ON users_{env}(auth0_id);
CREATE INDEX IF NOT EXISTS idx_users_{env}_email ON users_{env}(email);
```

Note: Uses TEXT for id/timestamps to match the existing `job_listings` convention (not ideal, but consistent). Future `saved_filters` and `saved_companies` tables should use the same pattern with `user_id TEXT REFERENCES users_{env}(id)`.

**Key patterns to follow:**
- Connection pool: Use `get_db` dependency from `dependencies.py` for database connections
- Models: Use `ConfigDict(alias_generator=to_camel, populate_by_name=True)` for camelCase JSON
- Table names: Use `_get_table_name(env, "users")` pattern
- Tests: Real PostgreSQL with module-scoped fixtures, override auth dependency in test app
- Environment: Access `request.app.state.env` for environment name in routers

**JWT validation approach:**
```python
# src/backend/api/auth/jwt.py
from jwt import PyJWKClient
import jwt

_jwks_client: PyJWKClient | None = None

def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
    return _jwks_client

def validate_token(token: str) -> dict:
    client = _get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token, signing_key.key,
        algorithms=["RS256"],
        audience=settings.auth0_audience,
        issuer=f"https://{settings.auth0_domain}/",  # Auth0 issuers have a trailing slash
    )
```

**Auth dependencies:**
```python
# src/backend/api/auth/dependencies.py
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_bearer_scheme = HTTPBearer(auto_error=False)

async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict | None:
    if credentials is None:
        return None
    try:
        return validate_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (jwt.InvalidTokenError, PyJWKClientError):
        raise HTTPException(status_code=401, detail="Invalid token")
    # Let unexpected errors (network, config) propagate as 500s for visibility

async def get_current_user(
    user: dict | None = Depends(get_optional_user),
) -> dict:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
```

**User service (upsert pattern):**
```python
# GET /api/users does double-duty: validates token AND creates/updates user
# Uses ON CONFLICT (auth0_id) DO UPDATE for atomic upsert
# NOTE: picture_url is ONLY set here (from JWT claims), never from user input via PUT
def get_or_create_user(conn, env, auth0_id, email, given_name, family_name, picture_url):
    table = _get_table_name(env, "users")
    cursor = conn.cursor()
    cursor.execute(f"""
        INSERT INTO {table} (id, auth0_id, email, given_name, family_name, picture_url, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (auth0_id) DO UPDATE SET
            email = EXCLUDED.email,
            given_name = EXCLUDED.given_name,
            family_name = EXCLUDED.family_name,
            picture_url = EXCLUDED.picture_url,
            updated_at = EXCLUDED.updated_at
        RETURNING *
    """, (uuid4_str, auth0_id, email, given_name, family_name, picture_url, now, now))
    conn.commit()
    return dict(cursor.fetchone())
```

---

### Unit 2: Frontend -- Auth Integration + Account Page

**Files to create:**
- `src/frontend/src/config/auth.ts` -- Centralized Auth0 config from `import.meta.env.VITE_AUTH0_*` vars, `isEnabled` flag
- `src/frontend/src/features/auth/useAuth.ts` -- Thin wrapper around `useAuth0()` adding `isEnabled` check
- `src/frontend/src/features/auth/authService.ts` -- `fetchCurrentUser(token)` and `updateCurrentUser(token, updates)` fetch utilities for `/api/users`
- `src/frontend/src/components/layout/UserMenu.tsx` -- Avatar + dropdown menu (Account link, Sign Out) when authenticated, "Sign In" button when not
- `src/frontend/src/pages/AccountPage/AccountPage.tsx` -- User profile page with avatar, name, email (read-only), display name editing

**Files to modify:**
- `src/frontend/package.json` -- Add `@auth0/auth0-react` dependency
- `src/frontend/src/main.tsx` -- Wrap app with `<Auth0Provider>` (outside Redux Provider, inside ErrorBoundary)
- `src/frontend/src/components/layout/GlobalAppBar.tsx` -- Add `<UserMenu />` to right side of Toolbar (use `flexGrow: 1` spacer after title)
- `src/frontend/src/config/routes.ts` -- Add `ACCOUNT: '/account'` to ROUTES (NOT to NAV_ITEMS -- accessible via user menu only)
- `src/frontend/src/app/App.tsx` -- Add `<Route path={ROUTES.ACCOUNT} element={<AccountPage />} />`
- `src/frontend/src/components/layout/NavigationDrawer.tsx` -- Add Account link at bottom of drawer (only shown when authenticated)

**Auth0Provider placement in main.tsx:**
```tsx
// Auth0Provider wraps outside Redux Provider, inside ErrorBoundary
<ErrorBoundary>
  <Auth0Provider
    domain={AUTH_CONFIG.domain}
    clientId={AUTH_CONFIG.clientId}
    authorizationParams={{
      redirect_uri: AUTH_CONFIG.redirectUri,
      audience: AUTH_CONFIG.audience,
      scope: "openid profile email",
    }}
  >
    <Provider store={store}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <App />
      </ThemeProvider>
    </Provider>
  </Auth0Provider>
</ErrorBoundary>
```

Key differences from other providers:
- `redirect_uri` is nested inside `authorizationParams`, not a top-level prop
- No separate `logoutUri` prop -- passed to `logout()` call as `logoutParams.returnTo`
- `audience` is nested inside `authorizationParams`
- Must explicitly request `scope: "openid profile email"`

**useAuth wrapper (`src/frontend/src/features/auth/useAuth.ts`):**
```typescript
import { useAuth0 } from '@auth0/auth0-react';
import { AUTH_CONFIG } from '../../config/auth';

export function useAuth() {
  const {
    isAuthenticated,
    isLoading,
    user,
    loginWithRedirect,
    logout,
    getAccessTokenSilently,
  } = useAuth0();

  return {
    isEnabled: AUTH_CONFIG.isEnabled,
    isAuthenticated: AUTH_CONFIG.isEnabled && isAuthenticated,
    isLoading: AUTH_CONFIG.isEnabled && isLoading,
    user,
    login: () => loginWithRedirect(),
    logout: () => logout({ logoutParams: { returnTo: window.location.origin } }),
    getToken: () => getAccessTokenSilently(),
  };
}
```

**UserMenu component behavior:**
- Not authenticated: MUI `Button` "Sign In" --> calls `login()`
- Authenticated: MUI `IconButton` with `Avatar` (user picture or initials) --> opens `Menu` with:
  - User name + email (disabled `MenuItem`)
  - `Divider`
  - "Account" --> `navigate('/account')`
  - "Sign Out" --> calls `logout()`
- Auth disabled (`!isEnabled`): Render nothing

**Account page layout:**
- MUI `Container` + `Paper` (matches WhyPage pattern)
- Large `Avatar` with user picture
- `TextField` for display name (editable)
- Read-only fields: email, given name, family name
- "Save Changes" `Button` --> calls `updateCurrentUser()`
- If not authenticated: show "Sign in to view your account" with `Button` --> `login()`

**Key patterns to follow:**
- MUI components: Use existing theme, no custom styles beyond what's needed
- Routing: Add route inside the `<Route path="/" element={<RootLayout />}>` group
- Auth service: Simple `fetch()` calls with `Authorization: Bearer ${token}` header, not RTK Query (user API is infrequent)

---

### Unit 3: Infrastructure -- Vercel Proxy + Config

**Files to create:**
- `api/users.ts` -- Vercel serverless proxy for `/api/users/*` endpoints, following `api/jobs-qa.ts` catch-all pattern. **Must forward `Authorization` header** to backend.

**Files to modify:**
- `vercel.json`:
  - Add rewrite: `{ "source": "/api/users/:path(.*)", "destination": "/api/users?path=:path" }`
  - Add SPA fallback: `{ "source": "/account", "destination": "/index.html" }`
  - Update CORS headers: Add `Authorization` to `Access-Control-Allow-Headers`, add `PUT` to `Access-Control-Allow-Methods`
  - **SECURITY: Replace `Access-Control-Allow-Origin: "*"` with the actual production Vercel domain** (e.g., `"https://yourapp.vercel.app"`). The current wildcard allows any website to make API requests to the backend. This must be fixed before shipping auth.

**Critical: `api/users.ts` must forward auth headers (unlike existing proxies):**
```typescript
// Follow api/jobs-qa.ts catch-all pattern but forward Authorization header
const headers: Record<string, string> = {
  Accept: 'application/json',
  'Content-Type': 'application/json',
};
if (req.headers.authorization) {
  headers['Authorization'] = req.headers.authorization;
}

const fetchOptions: RequestInit = {
  method: req.method,
  headers,
};

// Forward body for PUT/POST requests (guard against undefined/non-object body)
if ((req.method === 'PUT' || req.method === 'POST') && req.body != null) {
  fetchOptions.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
}
```

---

## Auth0 Dashboard Setup (Required)

### 1. Create Application
1. Auth0 Dashboard > Applications > Create Application
2. Type: **Single Page Application**
3. Settings > Allowed Callback URLs: `http://localhost:3000, https://yourapp.vercel.app`
4. Settings > Allowed Logout URLs: `http://localhost:3000, https://yourapp.vercel.app`
5. Settings > Allowed Web Origins: `http://localhost:3000, https://yourapp.vercel.app` (required for silent token renewal)
6. Note the **Client ID** and **Domain**

### 2. Create API
1. Auth0 Dashboard > Applications > APIs > Create API
2. Set a name and **Identifier** (audience) -- e.g., `https://yourapp.vercel.app/api`
3. Signing Algorithm: RS256

### 3. Create Post Login Action (CRITICAL)
Auth0 access tokens for custom APIs don't include profile claims by default. This Action adds them:

1. Auth0 Dashboard > Actions > Flows > Login
2. Add a custom Action (Post Login trigger):

```javascript
exports.onExecutePostLogin = async (event, api) => {
  api.accessToken.setCustomClaim('email', event.user.email);
  api.accessToken.setCustomClaim('given_name', event.user.given_name);
  api.accessToken.setCustomClaim('family_name', event.user.family_name);
  api.accessToken.setCustomClaim('picture', event.user.picture);
};
```

3. Deploy the Action and add it to the Login flow

Without this Action, the backend JWT will only contain `sub` -- user creation will have empty profile fields.

### 4. Enable Google Social Connection
1. Auth0 Dashboard > Authentication > Social
2. Enable **Google / Gmail**
3. Configure with Google OAuth credentials (or use Auth0's dev keys for testing)

---

## E2E Test Recipe

Auth requires real Auth0 credentials, so full e2e flow can't be automated in CI. Per-unit verification:

**Unit 1 (Backend):** `cd src/backend && pytest -v` -- tests mock the auth dependency, so no Auth0 credentials needed

**Unit 2 (Frontend):** `npm run type-check && npm test` -- tests mock `@auth0/auth0-react` via `vi.mock()`, verify component rendering and user interactions

**Unit 3 (Infrastructure):** `npm run build` -- verify the build succeeds with new config

**Manual e2e (after all units merged):**
1. Set up Auth0 account, create SPA application, create API, add Post Login Action, enable Google social
2. Set env vars in `.env.local`:
   - `VITE_AUTH0_CLIENT_ID` -- from Auth0 application settings
   - `VITE_AUTH0_DOMAIN` -- e.g., `yourapp.us.auth0.com`
   - `VITE_AUTH0_REDIRECT_URI` -- `http://localhost:3000`
   - `VITE_AUTH0_AUDIENCE` -- API identifier from Auth0
3. Set `AUTH0_DOMAIN`, `AUTH0_AUDIENCE` in backend env
4. Run `npm run dev:vercel`
5. Click "Sign In" --> Auth0 Universal Login --> Google OAuth --> redirect back --> verify user menu appears with avatar
6. Navigate to `/account` --> verify profile page with user info
7. Click "Sign Out" --> verify user menu returns to "Sign In" button

---

## Environment Variables

### Frontend (Vercel + .env.local)
| Variable | Description | Example |
|----------|-------------|---------|
| `VITE_AUTH0_CLIENT_ID` | Auth0 app client ID | `abc123def456` |
| `VITE_AUTH0_DOMAIN` | Auth0 tenant domain | `yourapp.us.auth0.com` |
| `VITE_AUTH0_REDIRECT_URI` | Post-login redirect | `http://localhost:3000` (dev) / `https://yourapp.vercel.app` (prod) |
| `VITE_AUTH0_AUDIENCE` | API identifier | Configured in Auth0 APIs dashboard |

Note: No separate `LOGOUT_URI` -- Auth0 passes this via `logout({ logoutParams: { returnTo: ... } })`.

### Backend (Railway)
| Variable | Description | Example |
|----------|-------------|---------|
| `AUTH0_DOMAIN` | Auth0 tenant domain (for JWKS) | `yourapp.us.auth0.com` |
| `AUTH0_AUDIENCE` | API identifier (for JWT validation) | Must match frontend audience |

---

## Future Extensibility (Not Implemented Now)

Design notes for saved filters and saved companies tables:

```sql
-- saved_filters_{env}: Store user's filter configurations
-- id TEXT PRIMARY KEY
-- user_id TEXT NOT NULL REFERENCES users_{env}(id) ON DELETE CASCADE
-- name TEXT NOT NULL
-- filter_type TEXT CHECK (filter_type IN ('graph', 'list', 'recent'))
-- filter_data JSONB NOT NULL  (serialized filter state)
-- created_at TEXT NOT NULL
-- updated_at TEXT NOT NULL

-- saved_companies_{env}: Store user's favorited companies
-- id TEXT PRIMARY KEY
-- user_id TEXT NOT NULL REFERENCES users_{env}(id) ON DELETE CASCADE
-- company_id TEXT NOT NULL
-- created_at TEXT NOT NULL
-- UNIQUE(user_id, company_id)
```

These tables will be added when the saved filters/companies feature is implemented. The `users` table's `id` column serves as the foreign key target.

---

## Gotchas and Risks

1. **Auth0 callback URLs:** Both `localhost:3000` (Vite/Vercel dev) and the production Vercel URL must be registered in Auth0 dashboard. Auth0 also requires **Allowed Web Origins** for silent token renewal -- missing this causes `login_required` errors after token expiry. Preview deployments may need wildcard URLs.
2. **Token audience mismatch:** `audience` in Auth0Provider's `authorizationParams` must match the Auth0 API identifier, which must match `AUTH0_AUDIENCE` in backend. If any differ, JWT validation fails silently with "invalid audience."
3. **Auth0 Action required for profile claims:** Without the Post Login Action, the access token only contains `sub`. The backend's `get_or_create_user` will save empty `email`, `given_name`, `family_name`, and `picture_url`. This is the most common Auth0 integration mistake.
4. **Auth0 issuer has trailing slash:** The JWT issuer is `https://yourapp.us.auth0.com/` (with trailing slash). The backend's `validate_token` must match this exactly or tokens will be rejected with "invalid issuer."
5. **Auth0 sub format varies by connection:** Email/password users get `auth0|abc123`, Google social users get `google-oauth2|abc123`. The `auth0_id` column handles any format since it's TEXT.
6. **CORS with Authorization header:** Current `vercel.json` CORS headers don't include `Authorization`. Browsers block preflight requests for authenticated API calls without this. **Must update.**
7. **Auth0 app type:** Must be "Single Page Application" (not "Regular Web Application") for the React SDK's silent token refresh and PKCE flow to work. Auth0 uses rotating refresh tokens for SPAs by default.
8. **Backend CORS:** Railway's `CORS_ORIGINS` setting must include the Vercel production domain.
9. **Auth is optional:** Every component using `useAuth()` must handle `isEnabled: false`. UserMenu renders nothing when auth is disabled.
