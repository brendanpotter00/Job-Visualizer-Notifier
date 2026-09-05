# Why This Was Built — `/why` (`ROUTES.WHY`)

A static "about" page. No data, no filters, no side effects — documented here so the
map is complete and a maintainer knows it is deliberately tool-free, not overlooked.

Page: `src/frontend/src/pages/WhyPage/WhyPage.tsx`.

## Sub-features

- **Static copy** — the project's rationale. Nothing dynamic, nothing to arrange or assert
  beyond "the page renders".

## How to get to it (user POV)

Sidebar (INFO group) "Why This Was Built", route `/why`. Public.

## Driving it with WebMCP

**No WebMCP tool applies** — the 14 tools drive jobs, filters, companies, auth and feedback,
none of which this page touches. To verify reachability, navigate the real router and read
the DOM directly (no shim call needed):

```ts
await page.goto('/why');
await expect(page.getByRole('heading', { level: 1 })).toBeVisible();   // the page's H1 renders
```

This is the one route whose "drive" is a plain navigation + a render check, by design.

## Gotchas

- **Nothing to assert past rendering.** Do not invent a tool call for it; a WebMCP drive here
  would be theater. The honest proof is "the route loads and its heading renders".
- **Reachable signed-out** — no auth, no flag. If it 404s, the router registration
  (`App.tsx`) is the thing to check, not any tool.
