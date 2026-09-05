# e2e/live-view — does the live view stay on screen?

```bash
e2e/run.sh live-view                 # the gate. 5 sessions, ~3.5 min, $0
e2e/run.sh live-view --case LV-02    # one scenario
e2e/run.sh live-view --live          # one REAL Browserbase discovery (~1 billed minute)
```

## Why this exists

The discovery live view — the embedded Browserbase iframe you watch while a company's
job feed is being found — has been reported fixed twice and was not. Both times the
reasoning was sound and the only evidence was a person describing a screen: *"it goes in
and out extremely fast."*

A unit test could not have caught any of it. The bugs lived in things jsdom does not
have: a real cross-origin iframe, a real `postMessage` from a page we do not own, the
real gap between two fulfilled polls — and, in the end, **a URL long enough to be
truncated**. So this gate runs the real frontend in a real browser and **measures** the
frame instead of describing it.

## What it found

Both earlier fixes were in the frontend, and the frontend was not where the bug was.
`--live` and the `frame-shots/` it captures settled it in one run:

| | |
|---|---|
| Symptom | the frame appeared and vanished ~1s later, every run |
| First theory | the frame's `browserbase-disconnected` closer was sticky |
| What the picture showed | the frame really was dead — it was painting *"Debugging connection was closed. Reason: WebSocket disconnected"* |
| Actual cause | **`progress.py` clipped every URL at 400 characters. Browserbase's `debuggerFullscreenUrl` is 479.** The iframe was loading a truncated `?wss=` parameter, so its socket died ~700ms after every load |
| Confirmation | seven probe mounts using the *raw* URL never disconnected; eleven product mounts using the *stored* URL all did |

The frontend's closer was reporting the truth all along. After the fix, a real capture
keeps the frame on screen for **95% of the session** (measured; it was 7%).

## Who owns what (this gate is not the only drive on this panel)

The `verify-onesecondswe` skill carries a second drive against the same panel,
`.claude/skills/verify-onesecondswe/helpers/live_view.spec.ts` (`@live-view`). It exists
because of the blind spot named below, and the two do **not** assert the same thing:

| | Subject | List endpoint | Cost |
|---|---|---|---|
| **this gate**, LV-01..LV-05 | **Continuity** — is the frame on screen from first paint until the session really ends, and which closer fired when it is not | scripted (`standin.ts`) | $0 |
| **skill** `@live-view` | **URL integrity + liveness** — is the URL that reaches the `<iframe src>` byte-identical to what the ledger was handed, and is the frame *alive* rather than merely mounted | real | $0 |

Keep it that way. Continuity needs a scriptable list endpoint, which is what makes this
gate blind to a mangled URL; integrity needs a real one, which is what stops that drive
from being able to place a poll and a disconnect in a chosen order. The **one** thing they
shared — the stand-in frame server — now has a single home here:
`serveVendorLikeStandIn` in [`standin.ts`](standin.ts), beside `serveStandIn`, imported by
the skill. If the stand-in moves, both callers move with it.

## What it asserts

One thing, five ways:

> **The frame is continuously on screen from the moment it first appears until the
> session genuinely ends.**

A gap is a failure, and the failure message names the closer that caused it:

```
The live view went blank while the session was still open.
  first gap: 20068ms from t=5932ms (never came back)
  CLOSER THAT FIRED: postMessage (sticky=true) at t=5944ms
```

The other half matters just as much and is asserted too: **the frame must really go when
the session is over.** A frame that outlives its session paints Browserbase's *"Debugging
connection was closed"* into our layout, which is what every closer exists to prevent.

| Case | The session | Asserts |
|---|---|---|
| `LV-01` | healthy start to finish | on screen throughout; gone within 8s of the server's retraction |
| `LV-02` | the frame posts one spurious `browserbase-disconnected` 1.2s after loading | recovers within one poll and stays up — defence in depth, since a third-party hint must never be able to end a session by itself |
| `LV-03` | one poll takes 13.5s, longer than the 12s trust lease | the lease expires (correct) but is *soft*, so the late payload restores the frame; the blink is bounded |
| `LV-04` | genuinely ends, server retracts promptly | frame goes at the disconnect and does not come back |
| `LV-05` | genuinely ends, server's null is a poll late | **no** re-appearance — the stale payload that still carries the URL must not remount the iframe onto a dead session |

## How it is instrumented

`src/frontend/src/components/my-companies/liveViewDebug.ts` makes the component narrate
itself, one greppable line per transition:

```
[live-view] url-arrived url=www.browserbase.com receivedAt=1788534393516 t=8241
[live-view] frame-load url=www.browserbase.com t=9145
[live-view] closer-fired which=postMessage sticky=true count=1 t=10205
[live-view] lease-rearmed receivedAt=1788534397555 windowMs=12000 t=12229
[live-view] phase phase=ending t=10215
```

`which=` is the field that answers the question — *what closed it* — and its values are a
closed union: `postMessage`, `frame-load-timeout`, `lease`, `session-ttl`,
`server-retraction`.

**It cannot ship on.** `import.meta.env.DEV` is statically false in a production build, so
the calls are dropped at build time; on top of that the page must set
`window.__JVN_LIVE_VIEW_DEBUG__` before React mounts, which only `addInitScript` can do.
The unit suite and the dev server stay silent.

Alongside the narration, `timeline.ts` samples the iframe's presence in the DOM every
50ms, so "was it on screen" is answered for every instant rather than the two an
assertion happens to check.

## What is faked, and what is not

Only two seams, and the reason is that a real Browserbase session costs money, lasts ~31
seconds, and cannot be asked to drop its socket at t=1.2s and then keep painting:

- **the hosted iframe** → `standin.ts` serves a page from `https://live-view.stand-in.test`
  via `page.route`. It is a genuine cross-origin document in a real browser doing a real
  `postMessage` with `targetOrigin: '*'`, so the component's origin check is a real check.
- **`GET /api/users/companies`** → answered from a script, which is what makes the ORDER
  of a poll and a disconnect choosable. Both bugs so far were about that order.

Everything else is the product: the real frontend, the real e2e backend on `:8201`, a
real signed-in user (`e2e/shared/auth/mint.py`), RTK Query's real 4s poll, React's real
timers, and a real `<iframe>`.

**The stand-in's two disconnect modes are measured, not invented** — see `StandInOptions`:

- `blipAfterMs` — once per *session*, never again however often the frame remounts.
  Measured: four remounts across a healthy session produced no message at all.
- `dieAfterMs` — from then on, ~600ms after *every* load. Measured: 626ms.

Getting this wrong is not cosmetic. A stand-in that blipped once per *mount* would have
made the correct fix look broken.

## `--live`

One real discovery of `atlassian.com/company/careers/all-jobs`, which opens one real
Browserbase session and mounts Browserbase's own frame.

**This is the mode that found the bug, and nothing cheaper could have.** The
deterministic gate serves its own stand-in at its own URL, so it can prove every closer
in the component and still be blind to a URL the backend mangled on the way out. `--live`
also writes `frame-shots/` — a picture of the iframe every 4s — which is the only way to
tell "the frame is mounted" from "the frame is painting a browser". Those were opposite
answers on the same DOM, and the whole diagnosis turned on it. **If the live view ever
misbehaves again, run this and look at the pictures first.**

**The blind spot now has a $0 gate too.**
`.claude/skills/verify-onesecondswe/helpers/live_view.spec.ts` (`@live-view`) keeps the
list endpoint REAL — it arranges a `discovering` row through the product's own writers
(`add_discovering_placeholder` + `ProgressLedger` + `record_discovery_progress`) and
asserts the URL that comes back is byte-identical and carries no `…`, then reads what the
frame **painted**. That is the assertion `--live` used to be the only source of. `--live`
is still the only thing that exercises Browserbase's real frame, so it stays the tool for
"the live view is misbehaving again and I need pictures".

### The blink after the URL fix (LV-05)

The URL fix left one blink behind, and it took `--live` to see it. `browserbase-disconnected`
was made *disprovable* in the same commit — belt and braces — so a payload landing after it
put the frame back. But the backend's `live_view_url: null` is **structurally one poll
behind the socket**, so the payload that "disproves" a real ending is always the stale one:
it was fetched before the browser closed, which is exactly why it still carries the URL.

Measured across four `--live` runs at `047db740`:

| run | frame-load | first disconnect | gap | server retracted |
|---|---|---|---|---|
| `20260905T005745Z` | 19197ms | 45127ms | 25.9s | +1.8s |
| `20260905T005925Z` | 15529ms | 41057ms | 25.5s | **+4.7s** |
| `20260905T010148Z` | 9143ms | 34792ms | 25.6s | +2.5s |
| `20260905T010310Z` | 9685ms | 36556ms | 26.9s | +1.0s |

One message per session, every time, ~26s after the frame loaded. In run `005925Z` the
retraction was 4.7s behind it — longer than the 4s poll — so a payload landed 76ms after
the disconnect, remounted the iframe onto a released session, and it painted **nothing**
for 807ms before dying again. Real page → gone → white flash → gone. That run scored
**87% coverage** and would have passed a percentage-only assertion.

The fix is `LIVE_VIEW_FRAME_SETTLE_MS`: a disconnect from a frame that has been up longer
than one poll interval is the ending it says it is. Below that window it stays disprovable,
which is LV-02 — the one measurement that ever looked like a mid-session blip
(`20260904T150614Z`, 1.06s after load) is the pre-fix **clipped-URL** run, where the socket
genuinely died, so the softness is policy rather than an expected behaviour.

**Presence is not liveness — do not add a percentage-only assertion here.** Measured
across the regression: at `b86f5b1f` the frame was on screen for **98.7%** of the session
while painting *"Debugging connection was closed"* the entire time; at `e48257fe`, 4.7%
and blank; at `047db740` (the fix), 92.1% painting the real careers page. A frame nobody
unmounts scores near-perfect while being completely dead, so coverage must always be read
next to something that says what the frame *rendered*.

It runs `stack_app.py`, the only entrypoint in this repo that permits
`CAPTURE_USE_BROWSERBASE=true`, with the guard inverted and every other guard kept. Cost:
one billed browser-minute (Browserbase rounds up, and the session is ~31s) plus one
Anthropic selection round.

## Cost and safety

- The default gate is **$0** and opens no session. The shared stack refuses to boot with
  `CAPTURE_USE_BROWSERBASE=true` or a Browserbase key set.
- It reuses the add-companies stack (`:8201` / `:3201`) and therefore takes the **same run
  lock**, so it can never tear down a gate that is mid-run.
- `retries: 0`, deliberately: this measures a timeline, and a retry would turn a real
  flicker into "it passed the second time".

## Artifacts

`artifacts/<RUN_ID>/` — `playwright-stdout.txt`, `playwright-report.json` (the full
narration is in every failure message), `stack/backend.log`, `stack/frontend.log`, plus
traces and screenshots on failure.
