"""The backend's door onto the one provider-date parser (POSTED-DATE-PLAN.md §5/U1).

The implementation lives in ``scripts/shared/posted_date.py``, not here, and this
module is a re-export rather than a copy. The reason is deployment, not taste:
``src/backend/Dockerfile`` copies ``src/backend/api/`` to ``/app/api`` and
``scripts/`` to ``/app/scripts``. So the backend is ``api.*`` in the container and
``src.backend.api.*`` in a local checkout, while ``scripts.*`` is the same name in
both. ``scripts/shared/batch_writer.py`` — which is loaded INSIDE the Railway
backend container, via ``scripts.shared.incremental`` — therefore cannot import a
module under ``api/`` and have it resolve everywhere. Putting the logic on the
``scripts`` side is the only arrangement where the published write path and the
custom write path run the same code, which is the entire point of U1.

Import from here on the backend side; the behaviour, the parse-safety window, and
the "never synthesize, never raise" contract are all documented on the source
module.
"""

from __future__ import annotations

from scripts.shared.posted_date import (  # noqa: F401
    FUTURE_SKEW_ALLOWANCE,
    effective_posted_date,
    parse_posted_date,
)

__all__ = ["FUTURE_SKEW_ALLOWANCE", "effective_posted_date", "parse_posted_date"]
