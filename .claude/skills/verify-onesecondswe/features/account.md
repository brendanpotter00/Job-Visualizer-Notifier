# Account / Auth — `/account` (`ROUTES.ACCOUNT`)

The account page and the sign-in entry point. `request_sign_in` maps the prompt
path; real Tier-3 authentication for verification comes from the harness fixture,
never from this tool.

Page: `src/frontend/src/pages/AccountPage/AccountPage.tsx`.
Auth: `src/frontend/src/features/auth/useAuth.ts` (`login` = `loginWithRedirect` / Google
One-Tap).

## Sub-features

- **Sign-in prompt** — `request_sign_in` triggers `useAuth().login()`. **No token ever
  reaches the agent.**
- **Account view** — once authenticated (via the fixture), the page shows the signed-in
  user's profile.

## How to get to it (user POV)

Sidebar / app-bar account entry, route `/account`. Signed-out visitors get the sign-in
prompt; signed-in visitors get their account view.

## Driving it with WebMCP

- **Smoke the prompt path (Tier-3):**
  ```ts
  const r = await call(page, 'request_sign_in');         // { prompted: true }
  ```
  This confirms the bridge captured `useAuth().login` and the prompt fires. It **cannot
  complete headlessly** (Auth0 full-page redirect / One-Tap), so there is nothing further to
  assert from it.
- **Real signed-in state** for any Tier-3 side-effect test comes from the fixture:
  `signedInPage` / `signedInContext` inject a JWKS-seam minted token via
  `e2e/shared/auth/storage_state.ts` (an `addInitScript` writing
  `localStorage['jvn.googleCredential.v1']`, read once at first render). Use those pages for
  `set_enabled_companies`, `save_filter_defaults`, `upvote_feature`.

## Gotchas

- **`request_sign_in` is smoke-only.** A `{ prompted: true }` return means the prompt path
  fired — it is NOT proof of a session. Do not chain a Tier-3 write after it and expect a
  token; use the fixture.
- **If `request_sign_in` returns an error** ("auth bridge is not mounted"), the
  `WebMcpBridge` did not mount — check `VITE_WEBMCP` is on and `App.tsx` rendered the bridge
  inside `<BrowserRouter>`.
- **Two identities exist** (`e2e/shared/auth/mint.py`): `PRIMARY_USER`
  (`e2e+add-companies@jvn.test`) for everything, and `OTHER_USER` (`e2e+other@jvn.test`) for
  ownership-isolation. `signInContext(context, 'primary'|'other')` signs a fresh context in.
