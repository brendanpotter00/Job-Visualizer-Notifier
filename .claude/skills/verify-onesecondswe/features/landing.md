# Marketing Landing — `/` (`ROUTES.HOME`)

The full-bleed marketing landing page, rendered **outside `RootLayout`** (no sidebar
chrome) so it reads like a standalone page. Static marketing copy + a 3D scene + a
sign-in CTA that feeds the top of the signup-conversion funnel, plus one live-data section
("Just Posted"). Documented here so the map is complete and a maintainer knows it is
deliberately tool-free, not overlooked.

Page: `src/frontend/src/pages/LandingPage/LandingPage.tsx`, rendered by `app/HomeRoute.tsx`.

## Sub-features

- **Static marketing sections** — header/hero and copy (`sections/LandingHeader.tsx`, …).
  Nothing to arrange or assert beyond "the page renders".
- **Sign-in CTA** — the funnel's mid-step; clicking it fires the same global login path
  `request_sign_in` would, not a landing-specific action.
- **"Just Posted" triptych** — real software-engineering jobs from three anonymous
  `GET /api/jobs/search` requests fired on mount. `fresh-jobs-skeleton` shows while they
  load, then `fresh-jobs-triptych` (slots `triptych-slot-early_career`,
  `triptych-slot-last_24h`, `triptych-slot-big_tech`). If any request fails, or every slot
  is empty, the section is not rendered at all. In each card, Apply is the job's real
  posting (new tab) and the rest of the card is a link to `/jobs` named
  "Browse all recent jobs".

## How to get to it (user POV)

`/`, signed out. A signed-in visitor at `/` is redirected to `/jobs` (the QA auth-bypass
user is not, so bypass builds show the page), and so is an old `/?category=…` filter link
(`app/homeDestination.ts`). Every unclaimed path — the old `/landing` and
`/admin/landing-prototypes` included — redirects to `/` with the query string and hash
preserved. Public — no auth, no flag.

## Driving it with WebMCP

**No WebMCP tool applies** — the 14 tools drive jobs, filters, companies, auth and feedback,
none of which this page touches. Verify reachability by navigating the real router and reading
the DOM directly (no shim call needed):

```ts
await page.goto('/');
await expect(page.getByTestId('landing-header')).toBeVisible();   // the page mounted
```

Like `/why`, this route's "drive" is a plain navigation + a render check, by design.

## Gotchas

- **Nothing to drive past rendering.** Do not invent a tool call; a WebMCP drive here would
  be theater. The honest proof is "the route loads and `landing-header` renders", plus,
  when the backend is reachable, `fresh-jobs-triptych` replacing `fresh-jobs-skeleton`.
- **Full-bleed, outside `RootLayout`** — no sidebar/app-bar chrome, so do not assert layout
  handles (the sidebar, the app bar) on this route.
- **Signed-in sessions skip it.** Drive it signed out (or on a bypass build); a signed-in
  context lands on `/jobs`. Redirects onto `/` must keep the query string and hash.
- **Reachable signed-out.** If it 404s, the router registration (`App.tsx`) is the thing to
  check, not any tool.
