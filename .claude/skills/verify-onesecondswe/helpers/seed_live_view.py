#!/usr/bin/env python3
"""verify-onesecondswe :: arrange ONE discovering row carrying a full-length live-view URL.

WHY THIS EXISTS, AND WHY IT WRITES THROUGH THE PRODUCT
=====================================================
`e2e/live-view` proves every closer in `DiscoveryChecklist`'s `LiveView`, and its
README states its own blind spot plainly: its deterministic mode answers
``GET /api/users/companies`` from `standin.ts`, so the URL the iframe receives is
the URL the TEST chose. It is therefore structurally incapable of noticing a URL the
BACKEND mangled on the way out — and that is exactly what the bug was. `progress.py`
clipped every URL in the discovery blob at 400 characters; Browserbase's
``debuggerFullscreenUrl`` measures 479; the iframe loaded a truncated ``?wss=`` and its
socket died ~700ms later. Only ``--live`` (one billed Browserbase minute) caught it.

So this helper arranges the row the way the PRODUCT does, and touches no clipping code
of its own:

* :func:`custom_companies_service.add_discovering_placeholder` creates the provisional
  ``health_state='discovering'`` company + ``user_companies`` row (the same call the 202
  add path makes), and
* :class:`discovery.progress.ProgressLedger` — constructed WITH the live-view URL, so
  ``_safe_live_view_url`` runs on the WRITE — is published through
  :func:`custom_companies_service.record_discovery_progress`, the same seam the
  discovery task publishes each step through.

``read_progress`` then applies the same bound again on the READ, inside the real
``GET /api/users/companies``. A clip at either end is a clipped ``<iframe src>``, which
is what the spec asserts against.

Nothing here fabricates a blob or hand-writes SQL against ``companies``: a seed that
built the JSON itself would re-acquire the very blindness it is here to remove.

DATABASE SAFETY is inherited, not re-implemented: the connection comes from
``e2e/shared/db/assertions.py::connect``, which refuses any database but
``jobscraper_e2e`` — the same guard `db_assert.py` and `reset_tier3.py` rely on.

Prints one JSON object on stdout for the spec to read::

    {"companyId": "u-…", "userId": "…", "liveViewUrl": "https://…", "urlChars": 479}

Run with the repo-root ``.venv`` python (an absolute path works from anywhere; this
file puts the repo root on ``sys.path`` itself)::

    .venv/bin/python .claude/skills/verify-onesecondswe/helpers/seed_live_view.py \
        --live-view-url 'https://live-view.stand-in.test/…'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Repo root on sys.path so both `e2e.*` and `src.backend.*` resolve regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from e2e.shared.auth.mint import PRIMARY_USER  # noqa: E402
from e2e.shared.db.assertions import connect  # noqa: E402
from src.backend.api.services import custom_companies_service as svc  # noqa: E402
from src.backend.api.services.discovery.progress import (  # noqa: E402
    STEP_OPEN_PAGE,
    ProgressLedger,
)
from src.backend.api.services.user_service import get_or_create_user  # noqa: E402

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/jobscraper_e2e"

# A URL no other section owns, so this row can never collide with `add-companies`'
# fixtures or `live-view`'s `u-liveview01`. `add_discovering_placeholder` is idempotent
# per (user_id, canonical_source_key), so a re-run reuses the same row rather than
# stacking a second one.
_BOARD_URL = "https://careers.live-view-url-probe.test/jobs"
_DISPLAY_NAME = "Live View URL Probe"


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed a discovering row with a live-view URL.")
    ap.add_argument(
        "--live-view-url",
        required=True,
        help="The hosted live-view URL to publish. The spec passes a stand-in URL "
        "padded to the measured length of Browserbase's debuggerFullscreenUrl.",
    )
    ap.add_argument("--dsn", default=_DEFAULT_DSN)
    args = ap.parse_args()

    conn = connect(args.dsn)
    try:
        # The signed-in fixture's token is minted offline against the JWKS seam, so the
        # `users` row only exists once some endpoint has resolved that identity. Create
        # it the way every authenticated route does rather than assuming a prior call.
        user = get_or_create_user(
            conn,
            auth0_id=PRIMARY_USER["sub"],
            email=PRIMARY_USER["email"],
            given_name=None,
            family_name=None,
            picture_url=None,
        )
        user_id = str(user["id"])

        row = svc.add_discovering_placeholder(
            conn,
            user_id=user_id,
            submitted_url=_BOARD_URL,
            normalized_url=_BOARD_URL,
            display_name=_DISPLAY_NAME,
        )

        # THE ONE LINE THIS FILE EXISTS FOR: the URL goes in through the product's own
        # ledger, so `_safe_live_view_url` decides what is stored.
        ledger = ProgressLedger(live_view_url=args.live_view_url)
        ledger.start(STEP_OPEN_PAGE)
        published = svc.record_discovery_progress(
            conn,
            user_id=user_id,
            normalized_url=_BOARD_URL,
            progress=ledger.snapshot(),
        )
        if not published:
            raise RuntimeError(
                "record_discovery_progress wrote nothing — the row is not in "
                "health_state='discovering' (a previous run may have settled it)"
            )

        print(
            json.dumps(
                {
                    "companyId": row["id"],
                    "userId": user_id,
                    "boardUrl": _BOARD_URL,
                    "liveViewUrl": args.live_view_url,
                    "urlChars": len(args.live_view_url),
                    # What the ledger ACTUALLY kept, so a caller that only reads stdout
                    # can already see a clip without going near the database.
                    "storedChars": len(ledger.live_view_url or ""),
                }
            )
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
