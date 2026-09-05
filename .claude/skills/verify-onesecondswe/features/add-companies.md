# Add Companies — `/add-companies` (`ROUTES.MY_COMPANIES`, flag-gated)

Paste a company's careers URL and track the company behind it: one press, one
outcome (add / one-time discovery / already-public link / refusal). **No new
WebMCP tool covers this** — it is verified by the dedicated `e2e/add-companies`
regression gate, and this file is the cross-reference so a reader knows where the
real coverage lives.

**This file owns the URL half of the box only.** The same input accepts a company
*name*, which takes an entirely different backend path (`POST /api/companies/search-by-name`,
a paid Browserbase Search behind it) with its own gate and its own rules —
[`company-name-search.md`](company-name-search.md).

Page: `src/frontend/src/pages/MyCompaniesPage/` (kept its pre-rename internal name).
Flag: `VITE_CUSTOM_COMPANIES_ENABLED === 'true'` (on in the e2e frontend env) **and**
backend `CUSTOM_COMPANY_SOURCES_ENABLED=true` (set in `env.e2e`). `/add-companies/:id`
(`MY_COMPANY_DETAIL`) and `/my-companies` (`MY_COMPANIES_LEGACY`, a redirect) are the
sub-paths; the same gate covers them.

## Sub-features

- **One-press add** — `POST /api/users/companies` resolves the pasted URL, adds an ATS board
  directly or routes a non-ATS URL into one-time discovery.
- **Already-public dedupe** — three checks (ATS `(ats, board_token)`, careers host, name-in-
  domain) short-circuit to `already_public` and write nothing; `matchKind` decides whether
  "Track anyway" is offered.
- **Discovery checklist / network log / live view** — the five-step setup narration (behind
  `VITE_DISCOVERY_PROGRESS_ENABLED`, also on in the e2e env).
- **Rename, delete/purge, monthly cap, ownership isolation, idempotent re-add,
  `trackAnyway` override.**

## How to get to it (user POV)

Sidebar "Add Companies" (only when the flag is on), route `/add-companies`. Sign-in
required. Signed-out shows the gate.

## Driving it with WebMCP

**There is no WebMCP tool for the add flow** — it is a form-driven, LLM-and-browser-backed
pipeline, not a store/endpoint the 14 tools wrap. Do not try to synthesize it from Tier-3
tools. Instead:

- **Verify it through its own gate:** `e2e/run.sh add-companies` (full), `--fast` (cheap
  subset), `--case AC-06` (one case). See `.claude/skills/e2e-gate/SKILL.md` and
  `e2e/add-companies/CASES.md`.
- **The user cases, mapped to gate cases** (assertions live in `CASES.md` — this only points):

  | User outcome | Gate case(s) |
  |---|---|
  | Careers-host dedupe (script boards), terminal — no way past | AC-01 (Microsoft), AC-02 (Amazon) |
  | Embedded-Workday careers URL adds and harvests | AC-03 (Cisco) |
  | Non-ATS URL → one-time discovery → VERIFIED | AC-04 (Atlassian), AC-05 (Jane Street) |
  | Name-in-domain match, "This isn't the same company" escape hatch | AC-06 / AC-06a (Spotify) |
  | Delete + purge + `ownerlessCount` delta + fresh re-add | AC-07 (Cisco) |
  | The full human add journey (paste → one press → success) | AC-08 (Cisco, UI) |
  | Feature flags off (sources / discovery) → 503 / `no_ats_detected` | AC-09 |
  | Ownership isolation (two users; 403 on jobs, 404 on delete) | AC-10 |
  | Idempotent re-add, zero extra spend | AC-11 (Atlassian) |
  | Server-side `trackAnyway` override still works | AC-12 (Microsoft) |

### The two exceptions

Two drives in this skill touch this route without the shim, each because of a coverage
hole its own gate could not reach:

| Drive | Owns | Cost |
|---|---|---|
| `helpers/live_view.spec.ts` `@live-view` | the discovery live-view URL reaches the iframe unclipped, and the frame is **alive** | $0 |
| `helpers/name_search.spec.ts` `@name-search` | the typed **name** reaches `search-by-name` byte-identical, and its answer reaches the screen — see [`company-name-search.md`](company-name-search.md) | $0 |

#### The discovery LIVE VIEW

`helpers/live_view.spec.ts` (`@live-view`) is the single drive in this skill that touches
this route, and it is here because of a coverage hole neither gate could reach:

- `e2e/live-view` scripts `GET /api/users/companies` from its own stand-in, so it is
  **structurally blind to a URL the backend mangled** — its README says so. That was the
  actual bug (`progress.py` clipped the 479-char `debuggerFullscreenUrl` at 400), and
  only `--live` (one billed Browserbase minute) caught it.
- This spec keeps the list endpoint **real** and arranges the row through the product's
  own writers instead, so the URL is asserted where it lands: on the wire, in the
  `<iframe src>`, and in what the frame paints. $0, no session opened.

It is still **not** shim-driven — there is no WebMCP tool for this surface, per below —
and it covers only URL integrity + liveness. Everything else about Add Companies remains
the `e2e/add-companies` gate's job, and the closers remain `e2e/live-view`'s.

## Gotchas

- **Its coverage is the gate, not this skill.** A green `verify-onesecondswe` run says
  nothing about Add Companies — with the two narrow exceptions above (`@live-view`,
  `@name-search`); run `e2e/run.sh add-companies` for the rest.
- **Presence is not liveness.** Measured across the live-view regression, the pre-closers
  commit scored **98.7%** on-screen while the frame painted *"Debugging connection was
  closed"* for the whole session. Never assert an on-screen percentage alone — assert the
  URL is unclipped, and read what the frame rendered.
- **Both flags must be on.** The e2e stack sets frontend `VITE_CUSTOM_COMPANIES_ENABLED=true`
  (via `src/frontend/.env.local`, picked up by `vite.e2e.config.ts`) and backend
  `CUSTOM_COMPANY_SOURCES_ENABLED=true` (`env.e2e`). With either off, the page/route is absent
  or the API 503s.
- **Discovery costs a live Claude Haiku call** on the full gate (AC-04/05/06). `--fast` is
  $0. Never point discovery at Browserbase — `env.e2e` pins `CAPTURE_USE_BROWSERBASE=false`
  and a blank key, asserted at boot by `e2e_app.py`.
- **The add flow's own `reset_user` sweep** (`cleanup.sh` step 2) deletes owned companies but
  **cannot** delete `company_add_attempts` (append-only audit) — the e2e monthly cap is
  raised to 100000 so re-runs never hit it.
