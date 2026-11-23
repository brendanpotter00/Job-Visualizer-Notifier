"""uvicorn entrypoint for the onboarding e2e backend: the shared `e2e_app` (its
database / Browserbase / auth-domain guards and the one patched JWKS seam) plus
one boot guard of this section's own.

PostHog must be OFF. Every case signs up a brand-new identity and most of them
finish or skip the questions, and the backend mirrors `user_signed_up`,
`onboarding_completed` and `onboarding_skipped` to PostHog whenever a project
token is set. A token reaching this process would put a dozen fake sign-ups
into the North Star funnel per run and break this section's "$0, no host but
its own stack" claim. `env.onboarding` blanks it; this refuses to boot if
anything put it back.
"""

from __future__ import annotations

from e2e.shared.stack.e2e_app import app  # noqa: F401 — runs the shared guards + patch

from api.config import settings  # noqa: E402

if settings.posthog_project_token:
    raise RuntimeError(
        "onboarding stack_app refuses to start: POSTHOG_PROJECT_TOKEN is set. This "
        "gate creates real-looking sign-ups and onboarding completions; with a token "
        "they would be mirrored to the production PostHog project. env.onboarding "
        "blanks it — run through e2e/run.sh onboarding."
    )

__all__ = ["app"]
