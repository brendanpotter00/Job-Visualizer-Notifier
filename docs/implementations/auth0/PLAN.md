# Auth0 Authentication Integration Plan

## Context

Add user authentication to the Job Posting Analytics app using Auth0 as the auth provider with **Google One Tap** for frictionless quick login. The app has a React frontend (Vite + Redux + MUI) deployed on Vercel and a Python FastAPI backend deployed on Railway with PostgreSQL. Auth is **optional** -- the app continues to work without login, but authenticated users will gain access to an Account page and (in the future) saved filters and saved companies.

**Two login methods:**
1. **Google One Tap** (primary, fast): On-page popup -- user clicks "Continue as [Name]" with no redirect. Uses Google Identity Services directly.
2. **Auth0 redirect** (fallback): "Sign In" button redirects to Auth0 Universal Login page for full OAuth flow.

**Architecture:**
- **Frontend** (`@auth0/auth0-react` + `@react-oauth/google`): Google One Tap prompt appears on page load for unauthenticated users. "Sign In" button triggers Auth0 redirect flow as fallback. Both flows produce a JWT that the frontend sends as a Bearer token.
- **Backend** (`PyJWT[crypto]`): Validates JWT access tokens from **both** Auth0 and Google against their respective JWKS endpoints. Does NOT use the Auth0 Python SDK -- the backend only needs to validate Bearer tokens, which is a standard JWT operation.
- **Database**: `users_{env}` table with email-based identity resolution to unify users across login methods.

**Why two login methods?** Google One Tap is the fastest possible login (one click, no redirect), but it only works for Google accounts and the token expires after ~1 hour with no silent refresh. Auth0 provides a full OAuth solution with silent token renewal, multiple provider support (future), and proper session management. Most users will log in via One Tap; the Auth0 redirect exists as a fallback.

**Identity resolution challenge:** The same Google user gets different `sub` values depending on login method:
- Auth0 Google social: `sub = "google-oauth2|12345"`
- Google One Tap: `sub = "12345"` (bare Google user ID)

The backend normalizes these to a consistent format and uses **email as the deduplication key** to ensure one database record per person regardless of login method.

---

## Work Units

### Unit 1: Backend -- Complete Auth Stack

**Status: Partially done.** Auth0 JWT validation, user service, and user router are implemented. Google One Tap support (dual JWKS validation, identity normalization) still needed.

**Files to create (new for Google One Tap):**
- `src/backend/api/auth/google_jwt.py` -- Google JWKS-based JWT validation for One Tap tokens

**Files already created (Auth0 -- DONE):**
- `src/backend/api/auth/__init__.py` -- Package init
- `src/backend/api/auth/jwt.py` -- Auth0 JWKS-based JWT validation using `PyJWKClient`
- `src/backend/api/auth/dependencies.py` -- `get_current_user` (required) and `get_optional_user` (optional) FastAPI dependencies using `HTTPBearer`
- `src/backend/api/services/user_service.py` -- `get_or_create_user()` (upsert via `ON CONFLICT`), `get_user_by_auth0_id()`, `update_user()`
- `src/backend/api/routers/users.py` -- `GET /api/users` (get-or-create current user), `PUT /api/users` (update profile)
- `src/backend/api/tests/test_users_router.py` -- Tests for user endpoints (mock auth dependency)
- `src/backend/api/tests/test_auth.py` -- Tests for JWT validation (generate test RSA keys)

**Files to modify (for Google One Tap):**
- `src/backend/api/config.py` -- Add `google_client_id` setting
- `src/backend/api/auth/jwt.py` -- Refactor into `validate_auth0_token()`, add `validate_token()` dispatcher that tries Auth0 first then Google
- `src/backend/api/auth/dependencies.py` -- Update `get_optional_user` to handle both token types via the unified `validate_token()`
- `src/backend/api/services/user_service.py` -- Add email-based lookup for identity resolution across login methods
- `src/backend/api/routers/users.py` -- Handle normalized identity from both token sources
- `src/backend/api/tests/test_auth.py` -- Add tests for Google token validation and the dual-validation dispatcher

**Files already modified (Auth0 -- DONE):**
- `scripts/shared/database.py` -- `users_{env}` table in `init_schema()`, `"users"` mapping in `_get_table_name()`
- `src/backend/api/config.py` -- `auth0_domain`, `auth0_audience` settings
- `src/backend/api/models.py` -- `UserResponse` and `UserUpdateRequest` Pydantic models
- `src/backend/api/main.py` -- Users router registered at `/api/users`
- `src/backend/api/requirements.txt` -- `PyJWT[crypto]>=2.8.0`
- `src/backend/api/tests/conftest.py` -- Users table cleanup, `_make_user`/`_insert_user` helpers, mock auth dependency fixture

**Database schema for `users_{env}`:**
```sql
CREATE TABLE IF NOT EXISTS users_{env} (
    id TEXT PRIMARY KEY,              -- UUID string (generated in Python)
    auth0_id TEXT NOT NULL UNIQUE,    -- Normalized external ID (see Identity Resolution below)
    email TEXT NOT NULL UNIQUE,       -- Also unique -- used for cross-method deduplication
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

Note: `email` now has a UNIQUE constraint (in addition to the existing index) to support cross-method identity resolution. Uses TEXT for id/timestamps to match the existing `job_listings` convention.

**Key patterns to follow:**
- Connection pool: Use `get_db` dependency from `dependencies.py` for database connections
- Models: Use `ConfigDict(alias_generator=to_camel, populate_by_name=True)` for camelCase JSON
- Table names: Use `_get_table_name(env, "users")` pattern
- Tests: Real PostgreSQL with module-scoped fixtures, override auth dependency in test app
- Environment: Access `request.app.state.env` for environment name in routers

**Dual JWT validation approach:**
```python
# src/backend/api/auth/jwt.py -- Updated to handle both Auth0 and Google tokens
from jwt import PyJWKClient
import jwt

_auth0_jwks_client: PyJWKClient | None = None
_google_jwks_client: PyJWKClient | None = None

def _get_auth0_jwks_client() -> PyJWKClient:
    global _auth0_jwks_client
    if _auth0_jwks_client is None:
        jwks_url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
        _auth0_jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
    return _auth0_jwks_client

def _get_google_jwks_client() -> PyJWKClient:
    global _google_jwks_client
    if _google_jwks_client is None:
        _google_jwks_client = PyJWKClient(
            "https://www.googleapis.com/oauth2/v3/certs",
            cache_keys=True, lifespan=3600,
        )
    return _google_jwks_client

def validate_token(token: str) -> dict:
    """Validate a JWT against Auth0 or Google JWKS. Returns claims dict with '_provider' key."""
    # Try Auth0 first (most common after initial login)
    if settings.auth0_domain:
        try:
            client = _get_auth0_jwks_client()
            signing_key = client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, signing_key.key,
                algorithms=["RS256"],
                audience=settings.auth0_audience,
                issuer=f"https://{settings.auth0_domain}/",
            )
            claims["_provider"] = "auth0"
            return claims
        except (jwt.InvalidTokenError, PyJWKClientError):
            pass

    # Fall back to Google ID token validation
    if settings.google_client_id:
        client = _get_google_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer="https://accounts.google.com",
        )
        claims["_provider"] = "google"
        return claims

    raise jwt.InvalidTokenError("No auth provider configured")
```

**Identity resolution in the router:**
```python
# src/backend/api/routers/users.py -- Updated for dual-provider support
@router.get("", response_model=UserResponse)
async def get_current_user_profile(request, conn, user):
    env = request.app.state.env
    provider = user.get("_provider", "auth0")

    # Normalize the external ID based on provider
    if provider == "google":
        auth0_id = f"google|{user['sub']}"
    else:
        auth0_id = user["sub"]  # e.g., "google-oauth2|12345"

    # Try upsert by auth0_id first, fall back to email match
    result = get_or_create_user(
        conn, env,
        auth0_id=auth0_id,
        email=user.get("email", ""),
        given_name=user.get("given_name"),
        family_name=user.get("family_name"),
        picture_url=user.get("picture"),
    )
    return UserResponse(**result)
```

**User service with email-based deduplication:**
```python
# src/backend/api/services/user_service.py -- Updated upsert
def get_or_create_user(conn, env, auth0_id, email, given_name, family_name, picture_url):
    table = _get_table_name(env, "users")
    now = datetime.now(timezone.utc).isoformat()

    # First, check if user exists by email (handles cross-method login)
    existing = _get_user_by_email(conn, env, email)
    if existing:
        # User exists -- update profile fields and auth0_id if different provider
        _update_profile(conn, env, existing["id"], auth0_id, given_name, family_name, picture_url)
        return _get_user_by_id(conn, env, existing["id"])

    # New user -- insert
    user_id = uuid.uuid4().hex
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, given_name, family_name, picture_url, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING *"
        ).format(sql.Identifier(table)),
        (user_id, auth0_id, email, given_name, family_name, picture_url, now, now),
    )
    conn.commit()
    return dict(cursor.fetchone())
```

**Auth dependencies (unchanged):**
```python
# src/backend/api/auth/dependencies.py -- No changes needed
# The unified validate_token() handles both token types transparently.
# get_optional_user and get_current_user work as before.
```

---

### Unit 2: Frontend -- Auth Integration + Account Page + Google One Tap

**Files to create:**
- `src/frontend/src/config/auth.ts` -- Centralized config from `import.meta.env.VITE_AUTH0_*` and `VITE_GOOGLE_CLIENT_ID` vars, `isEnabled` flag
- `src/frontend/src/features/auth/useAuth.ts` -- Thin wrapper around `useAuth0()` adding `isEnabled` check and Google One Tap state
- `src/frontend/src/features/auth/authService.ts` -- `fetchCurrentUser(token)` and `updateCurrentUser(token, updates)` fetch utilities for `/api/users`
- `src/frontend/src/features/auth/GoogleOneTap.tsx` -- Component that renders the One Tap prompt for unauthenticated users
- `src/frontend/src/components/layout/UserMenu.tsx` -- Avatar + dropdown menu (Account link, Sign Out) when authenticated, "Sign In" button when not
- `src/frontend/src/pages/AccountPage/AccountPage.tsx` -- User profile page with avatar, name, email (read-only), display name editing

**Files to modify:**
- `src/frontend/package.json` -- Add `@auth0/auth0-react` and `@react-oauth/google` dependencies
- `src/frontend/src/main.tsx` -- Wrap app with `<GoogleOAuthProvider>` and `<Auth0Provider>` (outside Redux Provider, inside ErrorBoundary)
- `src/frontend/src/components/layout/GlobalAppBar.tsx` -- Add `<UserMenu />` to right side of Toolbar (use `flexGrow: 1` spacer after title)
- `src/frontend/src/config/routes.ts` -- Add `ACCOUNT: '/account'` to ROUTES (NOT to NAV_ITEMS -- accessible via user menu only)
- `src/frontend/src/app/App.tsx` -- Add `<Route path={ROUTES.ACCOUNT} element={<AccountPage />} />`, add `<GoogleOneTap />`
- `src/frontend/src/components/layout/NavigationDrawer.tsx` -- Add Account link at bottom of drawer (only shown when authenticated)

**Provider placement in main.tsx:**
```tsx
// GoogleOAuthProvider wraps outermost (for One Tap), Auth0Provider inside it
<ErrorBoundary>
  <GoogleOAuthProvider clientId={AUTH_CONFIG.googleClientId}>
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
  </GoogleOAuthProvider>
</ErrorBoundary>
```

Key differences from other providers:
- `GoogleOAuthProvider` wraps outermost -- it only needs `clientId` (`VITE_GOOGLE_CLIENT_ID`, already in `.env.local`)
- Auth0's `redirect_uri` is nested inside `authorizationParams`, not a top-level prop
- No separate `logoutUri` prop -- passed to `logout()` call as `logoutParams.returnTo`
- Must explicitly request `scope: "openid profile email"` for Auth0

**Google One Tap component (`src/frontend/src/features/auth/GoogleOneTap.tsx`):**
```tsx
import { useGoogleOneTapLogin } from '@react-oauth/google';
import { useAuth } from './useAuth';

export function GoogleOneTap() {
  const { isEnabled, isAuthenticated, isLoading, setGoogleCredential } = useAuth();

  useGoogleOneTapLogin({
    onSuccess: (credentialResponse) => {
      if (credentialResponse.credential) {
        // Store Google ID token -- used as Bearer token for API calls
        setGoogleCredential(credentialResponse.credential);
      }
    },
    onError: () => {
      // Silent fail -- user can still use "Sign In" button
      console.warn('Google One Tap failed');
    },
    // Only show if auth is enabled AND user is not already logged in
    disabled: !isEnabled || isAuthenticated || isLoading,
  });

  return null; // Renders nothing -- One Tap UI is injected by Google's script
}
```

**useAuth wrapper (`src/frontend/src/features/auth/useAuth.ts`):**
```typescript
import { useState, useCallback } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { AUTH_CONFIG } from '../../config/auth';

export function useAuth() {
  const {
    isAuthenticated: isAuth0Authenticated,
    isLoading: isAuth0Loading,
    user: auth0User,
    loginWithRedirect,
    logout: auth0Logout,
    getAccessTokenSilently,
  } = useAuth0();

  // Google One Tap state (stored in memory -- not persisted)
  const [googleCredential, setGoogleCredential] = useState<string | null>(null);

  const isAuthenticated = AUTH_CONFIG.isEnabled && (isAuth0Authenticated || !!googleCredential);
  const isLoading = AUTH_CONFIG.isEnabled && isAuth0Loading;

  const getToken = useCallback(async () => {
    // Prefer Auth0 token (longer-lived, silently refreshable)
    if (isAuth0Authenticated) {
      return getAccessTokenSilently();
    }
    // Fall back to Google ID token (from One Tap)
    if (googleCredential) {
      return googleCredential;
    }
    throw new Error('Not authenticated');
  }, [isAuth0Authenticated, googleCredential, getAccessTokenSilently]);

  const logout = useCallback(() => {
    setGoogleCredential(null);
    if (isAuth0Authenticated) {
      auth0Logout({ logoutParams: { returnTo: window.location.origin } });
    }
  }, [isAuth0Authenticated, auth0Logout]);

  return {
    isEnabled: AUTH_CONFIG.isEnabled,
    isAuthenticated,
    isLoading,
    user: auth0User, // Auth0 user object (null for Google One Tap)
    login: () => loginWithRedirect(),
    logout,
    getToken,
    googleCredential,
    setGoogleCredential,
  };
}
```

**UserMenu component behavior:**
- Not authenticated: MUI `Button` "Sign In" --> calls `login()` (Auth0 redirect)
- Authenticated (either method): MUI `IconButton` with `Avatar` (user picture or initials) --> opens `Menu` with:
  - User name + email (disabled `MenuItem`)
  - `Divider`
  - "Account" --> `navigate('/account')`
  - "Sign Out" --> calls `logout()`
- Auth disabled (`!isEnabled`): Render nothing
- Google One Tap prompt appears automatically for unauthenticated users (no button needed)

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
- Google One Tap renders in `App.tsx` (inside providers), not in a layout component

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

Without this Action, the backend JWT will only contain `sub` -- user creation will have empty profile fields. (Not needed for Google One Tap -- Google ID tokens include profile claims by default.)

### 4. Enable Google Social Connection
1. Auth0 Dashboard > Authentication > Social
2. Enable **Google / Gmail**
3. Configure with Google OAuth credentials (or use Auth0's dev keys for testing)
4. **Use the same Google Client ID** as the one used for Google One Tap (`VITE_GOOGLE_CLIENT_ID`)

### 5. Google Cloud Console Setup (for One Tap)
The Google Client ID is already configured in `.env.local` as `VITE_GOOGLE_CLIENT_ID`. Ensure the Google Cloud Console project has:
1. OAuth consent screen configured
2. Authorized JavaScript origins: `http://localhost:3000, https://yourapp.vercel.app`
3. The OAuth client type is **Web application**

---

## E2E Test Recipe

Auth requires real credentials, so full e2e flow can't be automated in CI. Per-unit verification:

**Unit 1 (Backend):** `cd src/backend && pytest -v` -- tests mock the auth dependency, so no Auth0/Google credentials needed

**Unit 2 (Frontend):** `npm run type-check && npm test` -- tests mock `@auth0/auth0-react` and `@react-oauth/google` via `vi.mock()`, verify component rendering and user interactions

**Unit 3 (Infrastructure):** `npm run build` -- verify the build succeeds with new config

**Manual e2e (after all units merged):**
1. Set up Auth0 account, create SPA application, create API, add Post Login Action, enable Google social
2. Set env vars in `.env.local`:
   - `VITE_AUTH0_CLIENT_ID` -- from Auth0 application settings
   - `VITE_AUTH0_DOMAIN` -- e.g., `yourapp.us.auth0.com`
   - `VITE_AUTH0_REDIRECT_URI` -- `http://localhost:3000`
   - `VITE_AUTH0_AUDIENCE` -- API identifier from Auth0
   - `VITE_GOOGLE_CLIENT_ID` -- already configured
3. Set `AUTH0_DOMAIN`, `AUTH0_AUDIENCE`, `GOOGLE_CLIENT_ID` in backend env
4. Run `npm run dev:vercel`
5. **Test Google One Tap:** Page loads --> One Tap popup appears in top-right --> click "Continue as [Name]" --> verify user menu appears with avatar
6. **Test Auth0 redirect:** Sign out --> click "Sign In" button --> Auth0 Universal Login --> Google OAuth --> redirect back --> verify user menu appears
7. **Test identity unification:** Log in via One Tap first, sign out, then log in via Auth0 redirect --> verify same user record (check `/account` page shows same display name)
8. Navigate to `/account` --> verify profile page with user info
9. Click "Sign Out" --> verify user menu returns to "Sign In" button and One Tap prompt reappears

---

## Deployment Configuration

Steps to configure external services before deploying auth to production. Each step is labeled with whether it can be done via MCP server or requires manual action.

### Step 1: Auth0 -- Create SPA Application (MCP: `auth0_create_application`)

Create a Single Page Application in the Auth0 tenant (`dev-mbnkjr1sc4ccwlup.us.auth0.com`):

- **Type:** `spa`
- **Allowed Callback URLs:** `http://localhost:3000, https://job-visualizer-notifier.vercel.app`
- **Allowed Logout URLs:** `http://localhost:3000, https://job-visualizer-notifier.vercel.app`
- **Allowed Web Origins:** `http://localhost:3000, https://job-visualizer-notifier.vercel.app` (required for silent token renewal)

Save the **Client ID** from the response -- needed for frontend env vars.

### Step 2: Auth0 -- Create Custom API (MCP: `auth0_create_resource_server`)

Create an API resource server:

- **Name:** `Job Visualizer API`
- **Identifier (audience):** `https://job-visualizer-notifier.vercel.app/api`
- **Signing Algorithm:** RS256

The identifier becomes the `AUTH0_AUDIENCE` / `VITE_AUTH0_AUDIENCE` env var.

### Step 3: Auth0 -- Create Post Login Action (MCP: `auth0_create_action` + `auth0_deploy_action`)

Auth0 access tokens for custom APIs don't include profile claims by default. Create and deploy an action:

- **Trigger:** `post-login`
- **Code:**
```javascript
exports.onExecutePostLogin = async (event, api) => {
  api.accessToken.setCustomClaim('email', event.user.email);
  api.accessToken.setCustomClaim('given_name', event.user.given_name);
  api.accessToken.setCustomClaim('family_name', event.user.family_name);
  api.accessToken.setCustomClaim('picture', event.user.picture);
};
```

**After deploying via MCP, you must manually add it to the Login Flow:**
Auth0 Dashboard > Actions > Flows > Login > drag the action into the flow.
MCP cannot bind actions to flows -- this is a manual step.

### Step 4: Auth0 -- Enable Google Social Connection (Manual)

Auth0 Dashboard > Authentication > Social > enable **Google / Gmail**.
- Use the **same Google Client ID** as `VITE_GOOGLE_CLIENT_ID`
- This ensures Auth0's Google social login and Google One Tap share the same identity

### Step 5: Railway -- Set Backend Env Vars (MCP: `railway_set-variables`)

Set three new variables on the `Job-Visualizer-Notifier` service:

| Variable | Value |
|----------|-------|
| `AUTH0_DOMAIN` | `dev-mbnkjr1sc4ccwlup.us.auth0.com` |
| `AUTH0_AUDIENCE` | `https://job-visualizer-notifier.vercel.app/api` (from Step 2) |
| `GOOGLE_CLIENT_ID` | Same value as `VITE_GOOGLE_CLIENT_ID` from `.env.local` |

Existing `CORS_ORIGINS=https://job-visualizer-notifier.vercel.app` is already correct.

### Step 6: Vercel -- Set Frontend Env Vars (Manual -- Vercel Dashboard)

No Vercel MCP server available. Set these in Vercel Dashboard > Project Settings > Environment Variables:

| Variable | Value |
|----------|-------|
| `VITE_AUTH0_CLIENT_ID` | Client ID from Step 1 |
| `VITE_AUTH0_DOMAIN` | `dev-mbnkjr1sc4ccwlup.us.auth0.com` |
| `VITE_AUTH0_REDIRECT_URI` | `https://job-visualizer-notifier.vercel.app` |
| `VITE_AUTH0_AUDIENCE` | `https://job-visualizer-notifier.vercel.app/api` (from Step 2) |
| `VITE_GOOGLE_CLIENT_ID` | Same Google Client ID as `.env.local` |

### Step 7: Google Cloud Console (Manual)

Ensure the Google Cloud OAuth client is configured for production:

1. Add `https://job-visualizer-notifier.vercel.app` to **Authorized JavaScript origins**
2. Verify OAuth consent screen is configured
3. OAuth client type must be **Web application**

### Step 8: Security -- Restrict CORS Origin (Code Change)

`vercel.json` currently has `Access-Control-Allow-Origin: "*"`. Before shipping auth, restrict to:
```json
{ "key": "Access-Control-Allow-Origin", "value": "https://job-visualizer-notifier.vercel.app" }
```

---

## Environment Variables

### Frontend (Vercel + .env.local)
| Variable | Description | Example |
|----------|-------------|---------|
| `VITE_AUTH0_CLIENT_ID` | Auth0 app client ID | `abc123def456` |
| `VITE_AUTH0_DOMAIN` | Auth0 tenant domain | `yourapp.us.auth0.com` |
| `VITE_AUTH0_REDIRECT_URI` | Post-login redirect | `http://localhost:3000` (dev) / `https://yourapp.vercel.app` (prod) |
| `VITE_AUTH0_AUDIENCE` | API identifier | Configured in Auth0 APIs dashboard |
| `VITE_GOOGLE_CLIENT_ID` | Google OAuth client ID | Already in `.env.local` |

Note: No separate `LOGOUT_URI` -- Auth0 passes this via `logout({ logoutParams: { returnTo: ... } })`.

### Backend (Railway)
| Variable | Description | Example |
|----------|-------------|---------|
| `AUTH0_DOMAIN` | Auth0 tenant domain (for JWKS) | `yourapp.us.auth0.com` |
| `AUTH0_AUDIENCE` | API identifier (for JWT validation) | Must match frontend audience |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (for One Tap token validation) | Must match frontend `VITE_GOOGLE_CLIENT_ID` |

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

1. **Google One Tap token lifetime:** Google ID tokens expire after ~1 hour and cannot be silently refreshed. After expiry, the One Tap prompt reappears. For longer sessions, the user should use the Auth0 redirect flow (which supports silent token renewal). The frontend's `getToken()` should handle this gracefully.
2. **Identity resolution across login methods:** The same Google user gets `sub = "google-oauth2|12345"` from Auth0 and `sub = "12345"` from Google One Tap. The backend normalizes Auth0 subs to `google-oauth2|12345` and Google One Tap subs to `google|12345`. Since these are different, email is used as the deduplication key. The `email` column has a UNIQUE constraint.
3. **Google One Tap requires HTTPS in production:** One Tap only works on `localhost` (dev) or HTTPS origins. Vercel provides HTTPS by default, but local dev without `localhost` won't work.
4. **Google One Tap prompt dismissal:** If the user dismisses the One Tap prompt, Google suppresses it for a cooldown period (exponential: 2 hours, then 1 day, then 7 days, then 30 days). This is Google's behavior, not controllable by the app.
5. **Auth0 callback URLs:** Both `localhost:3000` (Vite/Vercel dev) and the production Vercel URL must be registered in Auth0 dashboard. Auth0 also requires **Allowed Web Origins** for silent token renewal -- missing this causes `login_required` errors after token expiry. Preview deployments may need wildcard URLs.
6. **Token audience mismatch:** Auth0 `audience` must match the Auth0 API identifier. Google One Tap `audience` must match `GOOGLE_CLIENT_ID`. These are different values validated by different JWKS endpoints -- don't mix them up.
7. **Auth0 Action required for profile claims:** Without the Post Login Action, the Auth0 access token only contains `sub`. Google One Tap tokens include profile claims by default -- no action needed for that flow.
8. **Auth0 issuer has trailing slash:** The JWT issuer is `https://yourapp.us.auth0.com/` (with trailing slash). Google's issuer is `https://accounts.google.com` (no trailing slash). The backend handles both.
9. **Google Client ID consistency:** The Google Client ID used in the frontend (`VITE_GOOGLE_CLIENT_ID`), backend (`GOOGLE_CLIENT_ID`), and Auth0 Google social connection MUST all be the same. Otherwise One Tap tokens won't validate or Auth0 won't recognize the Google user.
10. **CORS with Authorization header:** Current `vercel.json` CORS headers don't include `Authorization`. Browsers block preflight requests for authenticated API calls without this. **Must update.**
11. **Auth0 app type:** Must be "Single Page Application" (not "Regular Web Application") for the React SDK's silent token refresh and PKCE flow to work.
12. **Backend CORS:** Railway's `CORS_ORIGINS` setting must include the Vercel production domain.
13. **Auth is optional:** Every component using `useAuth()` must handle `isEnabled: false`. UserMenu renders nothing and GoogleOneTap is disabled when auth is disabled.
