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
| `LV-05` | genuinely ends, server's null is a poll late | at most **one** short re-appearance, then gone for good — the written-down price of a soft closer |

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
