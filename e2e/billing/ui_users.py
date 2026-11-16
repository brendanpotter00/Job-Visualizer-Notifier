"""Make a fresh user for a UI case and print it as JSON (the UI tier shells out
to this so users are created exactly the way the API tier creates them).

  python -m e2e.billing.ui_users free        -> a signed-up user, never paid
  python -m e2e.billing.ui_users admin       -> the same, plus an admins row
  python -m e2e.billing.ui_users subscriber  -> a paid subscription on its own
                                                test clock, already recorded
                                                pro/active by the webhook

Clocks made here are swept by run.sh's cleanup (`e2e-billing-*`).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_DIR = Path(__file__).resolve().parent / "api"
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "src" / "backend"), str(_API_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from conftest import DB_DSN, create_user, wait_for_row  # noqa: E402

from e2e.billing import stripe_env  # noqa: E402
from e2e.shared.db import assertions as db  # noqa: E402


def main(kind: str) -> int:
    if kind not in ("free", "admin", "subscriber"):
        print(__doc__, file=sys.stderr)
        return 2
    conn = db.connect(os.environ.get("E2E_DATABASE_URL", DB_DSN))
    conn.autocommit = True
    try:
        user = create_user(conn, admin=kind == "admin")
        out = {"sub": user.sub, "email": user.email, "userId": user.user_id}
        if kind == "subscriber":
            s = stripe_env.subscribe_on_clock(stripe_env.client(), user_id=user.user_id, email=user.email, label="ui")
            wait_for_row(conn, user.user_id, lambda r: r["status"] == "active" and r["plan"] == "pro",
                         "the webhook to record the UI subscriber as pro/active")
            out["clockId"] = s.clock_id
        print(json.dumps(out))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
