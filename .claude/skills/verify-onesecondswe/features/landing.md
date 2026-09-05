# Marketing Landing — `/landing` (`ROUTES.LANDING`)

The full-bleed marketing landing page, rendered **outside `RootLayout`** (no sidebar
chrome) so it reads like a standalone page. Static marketing copy + a 3D scene + a
sign-in CTA that feeds the top of the signup-conversion funnel. Documented here so the
map is complete and a maintainer knows it is deliberately tool-free, not overlooked.

Page: `src/frontend/src/pages/LandingPage/LandingPage.tsx` (lazy-loaded at the route).

## Sub-features

- **Static marketing sections** — header/hero and copy (`sections/LandingHeader.tsx`, …).
  Nothing to arrange or assert beyond "the page renders".
- **Sign-in CTA** — the funnel's mid-step; clicking it fires the same global login path
  `request_sign_in` would, not a landing-specific action.

## How to get to it (user POV)

**Direct URL only:** `/landing`. It is **deliberately unlisted** — no sidebar or nav entry
anywhere while it is iterated on (`routes.ts` says *"Do NOT add it to a nav array"*). The
pre-consolidation path `/admin/landing-prototypes` (`ROUTES.LANDING_LEGACY`) registers a
redirect onto `/landing` with the query string and hash preserved. Public — no auth, no flag.

## Driving it with WebMCP

**No WebMCP tool applies** — the 14 tools drive jobs, filters, companies, auth and feedback,
none of which this page touches. Verify reachability by navigating the real router and reading
the DOM directly (no shim call needed):

```ts
await page.goto('/landing');
await expect(page.getByTestId('landing-page')).toBeVisible();   // the page mounted
```

Like `/why`, this route's "drive" is a plain navigation + a render check, by design.

## Gotchas

- **Nothing to assert past rendering.** Do not invent a tool call; a WebMCP drive here would
  be theater. The honest proof is "the route loads and `landing-page` renders".
- **Full-bleed, outside `RootLayout`** — no sidebar/app-bar chrome, so do not assert layout
  handles (the sidebar, the app bar) on this route.
- **No nav entry by design.** If you cannot reach it from the UI, that is correct — go by URL.
  The redirect from `/admin/landing-prototypes` must keep the query string and hash.
- **Reachable signed-out.** If it 404s, the router registration (`App.tsx`) is the thing to
  check, not any tool.
