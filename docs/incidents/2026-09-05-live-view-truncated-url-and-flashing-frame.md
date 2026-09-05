# Incident: The Discovery Live View Never Worked — A 400-Character Clip, Hidden For Two Weeks

**Date:** 2026-08-20 (cause introduced) → 2026-09-05 (fixed). Visible as a bug from 2026-08-29.
**Severity:** Low impact, high process cost — a cosmetic feature, behind a flag, never in front of a user. But it was **declared fixed three times and was not**, and each wrong fix was defended with a passing test.
**Impact:** The live view — the embedded Browserbase iframe you watch while a company's job feed is discovered — never once streamed a live session between 2026-08-22 and 2026-09-04. For the first week it showed a **frozen dead frame** that looked plausible. After 2026-08-29 it **flashed and vanished within ~1.5s**. No data was lost, no scrape was affected, no user saw it (both flags default off).

## Summary

Three defects, discovered in the reverse order they were introduced, each one hiding the next.

1. **The cause (2026-08-20, `d410409f`).** `progress.py` clipped every stored URL at `_MAX_TEXT_CHARS = 400`. Browserbase's `debuggerFullscreenUrl` is **479 characters** — essentially one long signed `?wss=` parameter. We stored it 79 characters short with an ellipsis appended. The iframe connected to a mangled websocket address and its socket died **~700 ms after every load**.
2. **The disguise (2026-08-29, `7dd3319e`, squashed as `abe76b08`).** Three "closers" landed at once: a `browserbase-disconnected` postMessage handler, a **6-second permanent** trust lease, and a session TTL plus a 1.4s goodbye. None of them broke anything. They changed the *symptom* — from a dead frame nobody removed, to a dead frame removed after 1.5 seconds.
3. **The regression introduced while fixing it (2026-09-04, `047db740`).** `LIVE_VIEW_DISCONNECT_GRACE = 1`, added as "defence in depth", allowed the first disconnect to be disproved by a later poll — which let the iframe **remount onto a session that had already ended**, painting a blank white box for ~800 ms.

The clip predates the feature by two days. **There was never a regressing commit to find**, which is why bisecting for one wasted a cycle.

## Timeline

| Date | Commit | Event |
|---|---|---|
| 2026-08-20 | `d410409f` | `_MAX_TEXT_CHARS = 400` added; already applied to `live_view_url`. |
| 2026-08-22 | `fb491adf` | Live view ships, reading the 479-char `debuggerFullscreenUrl`. **Already broken** — but with no closers, the dead frame stays mounted and looks fine. |
| 2026-08-29 | `7dd3319e` | Three closers added. The dead frame now gets removed after ~1.5s. Symptom becomes "it comes in and out". |
| 2026-09-04 | `526268b0` | **Wrong fix #1** — lease widened 6s → 12s and made soft. Real bug (see below), not *this* bug. |
| 2026-09-04 | `047db740` | **Right fix** — `_MAX_LIVE_VIEW_URL_CHARS = 2048`. Also introduced the grace regression. |
| 2026-09-05 | `5918b5e1` | **Fix for the regression** — `LIVE_VIEW_FRAME_SETTLE_MS`; no remount onto an ended session. |

## The measurements that settled it

Three commits, one instrument, application source untouched at each:

| commit | URL served | clipped | coverage | what the frame **painted** |
|---|---|---|---|---|
| `b86f5b1f` (pre-closers) | 400 | yes | **98.7%** | *"Debugging connection was closed. Reason: WebSocket disconnected"* |
| `e48257fe` (believed good) | 400 | yes | 4.7% | blank |
| `047db740` (after the fix) | **479** | **no** | 92.1% | the real careers page |

The owner remembered `e48257fe` as working. It was not. Measuring it directly is what killed the "find the regression" theory.

## Root cause

**A generic string-clipper was applied to a value that is only useful intact.** `_safe_url` exists to bound log/JSON payload size, which is correct for human-readable text. A signed URL is not text — it is a credential. Truncating it does not degrade it, it **invalidates** it, and it does so silently: the value still looks like a URL, still passes every type check, and still renders in an `<iframe src>`.

The failure was then invisible because the thing that broke was **inside a cross-origin iframe we do not own**. Nothing in our stack could observe it. Our own logs showed a session created, a URL published, a frame mounted — all true, all healthy. The only witness was a pixel.

## Why every existing defense missed it

| Defense | Why it missed |
|---|---|
| Unit tests (jsdom) | No real iframe, no real cross-origin `postMessage`, no real network timing. The bugs lived in exactly those three. |
| The `DiscoveryChecklist` test suite | One test simulated 15 polls with a **0 ms round trip** — it advanced timers by exactly the poll interval and re-rendered instantly. Real latency was never in the test, which is why a 6s lease against a 5–7s real cadence shipped. |
| The `e2e/live-view` deterministic gate | Serves **its own** live-view URL, so it is structurally blind to a URL the *backend* mangled. Passed 5/5 throughout. |
| Coverage percentage | Measures **mountedness, not liveness**. `b86f5b1f` scored **98.7%** while painting a disconnect error for the entire session. Any percentage-only assertion passes a completely dead live view. |
| Two gates disagreeing | `LV-05` explicitly *tolerated* one short re-appearance; the `--live` spec *failed* on it. The grace regression lived in that disagreement. |
| Reasoning | Three consecutive diagnoses were confident, plausible, and wrong. The `browserbase-disconnected` handler was blamed twice; it was **reporting the truth** both times. |

## The fixes

| Fix | Where |
|---|---|
| Raise the cap for the live-view URL only, to 2048 (4× today's 479) | `progress.py` `_MAX_LIVE_VIEW_URL_CHARS`, `_safe_live_view_url` |
| Lease 6s → 12s and **soft** — a later poll re-confirming the same URL restores the frame | `DiscoveryChecklist.tsx` `LIVE_VIEW_TRUST_MS` |
| Do not remount onto a session that already ended | `DiscoveryChecklist.tsx` `LIVE_VIEW_FRAME_SETTLE_MS` |

## Prevention — what now makes this class of bug loud

1. **A URL-integrity assertion, not a coverage number.** `.claude/skills/verify-onesecondswe/helpers/live_view.spec.ts` checks the live-view URL end to end — ledger write → wire → `<iframe src>` — asserting it is **not truncated and carries no ellipsis**. Deterministic, `$0`, and it fails at every commit before `047db740`. This is the assertion that would have caught the original bug on day one.
2. **Liveness, not presence.** The same spec reads what the frame actually **painted** through `frameLocator`. A mounted frame showing a disconnect dialog now fails.
3. **A knob instead of an edit.** `LIVE_VIEW_SEED_CLIPPED=1` reproduces the clipped-URL failure without editing shared source — so proving a fix fails-first never again requires breaking the tree other people are running.
4. **`e2e/run.sh live-view --live`** measures a real session and writes `frame-shots/` every 4s. Its README states its own blind spot in writing: the deterministic mode cannot catch a backend-mangled URL.

### Rules worth keeping

- **Never clip a URL, a token, or a signature with a generic text limiter.** Bound them separately or not at all. A truncated credential fails silently and looks fine.
- **Presence is not liveness.** If a test can pass while the user sees a blank or broken box, it is not testing the feature.
- **A test with zero network latency is not a test of a polling system.**
- **When a component reports a failure, check whether it is right before silencing it.** Two rounds were lost muting an accurate messenger.
- **"It used to work" is a hypothesis, not evidence.** Measuring the remembered-good commit took one billed browser minute and refuted it immediately.

## Open, related, not fixed

`progress.py:416` still routes **preview job URLs** through the 400-char clip, and those render as `href`s — a job link over 400 characters becomes a dead link. Same bug class, much lower severity: a visible 404 rather than a silently killed socket.

## Cost

~10 billed Browserbase browser-minutes (≈ $0.02) across all investigation and verification. The expensive part was four rounds of engineering, three of which fixed the wrong thing.
