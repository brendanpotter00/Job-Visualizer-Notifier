# Feedback & Voting — `/vote-features` (`ROUTES.VOTE_FEATURES`)

The community feedback page: upvote candidate features and submit free-text
feedback. Shipped features move to a read-only "Shipped" section. Both Tier-3
writes are asserted by their DB side effect.

Page: `src/frontend/src/pages/VoteFeaturesPage/VoteFeaturesPage.tsx`.

## Sub-features

- **Upvote a feature** — `upvote_feature` (`POST /api/features/{id}/upvote`), sign-in
  required; optimistic patch + a `feature_upvotes` row.
- **Submit feedback** — `submit_feedback` (`POST /api/feedback`); works **signed-out**
  (stored anonymous) and signed-in; a `feedback` row either way.
- **Shipped section** — features with a `completedAt` render read-only (no upvote).

## How to get to it (user POV)

Sidebar (INFO group) "Give Feedback", route `/vote-features`. Feedback is public; upvoting
requires sign-in.

## Driving it with WebMCP

- **Submit feedback, signed-out (Tier-3, anonymous — no fixture needed):**
  ```ts
  const r = await call(page, 'submit_feedback', { message: 'verify-onesecondswe smoke …' });
  // r.submitted === true
  ```
  **DB proof** — a `feedback` row containing the marker:
  ```bash
  .venv/bin/python helpers/db_assert.py --table feedback --contains "verify-onesecondswe smoke"
  ```
- **Upvote a feature, signed-in (Tier-3):**
  ```ts
  const u = await call(signedInPage, 'upvote_feature', { featureId: 'mcp-server' });
  // u.featureId, u.upvoteCount, u.hasUpvoted === true
  ```
  **DB proof** — a `feature_upvotes` row:
  ```bash
  .venv/bin/python helpers/db_assert.py --table feature_upvotes \
    --email 'e2e+add-companies@jvn.test' --feature-id mcp-server
  ```
- **Seeded feature ids in the clone** (open candidates): `custom-dashboards`, `mcp-server`,
  `resume-match-ai` (from `list`-able features; 4 seeded total). Use one of these as
  `featureId`.

## Gotchas

- **`submit_feedback` is the ONE Tier-3 tool that is anonymous-capable** — drive it on a
  plain `page`; the row is stored with a NULL `user_id`. `db_assert.py --table feedback
  --contains …` finds it without an `--email`.
- **`upvote_feature` requires sign-in** — use `signedInPage`; without a token it returns an
  error result.
- **Message length cap is 5000** (`FEEDBACK_MAX_LENGTH`); an empty message is rejected by the
  tool before any request.
- **Upvote is idempotent per (user, feature)** — a second upvote by the same identity does
  not add a second row; assert the row EXISTS, not that the count grew by exactly one across
  re-runs (the sweep does not clear `feature_upvotes`).
