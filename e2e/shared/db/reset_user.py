"""Purge one test user and everything they own, through the product's OWN
delete path (PLAN.md §8) — never a hand-written `DELETE FROM job_listings`.

Runs BEFORE the suite too (a run killed at Ctrl-C must not poison the next
one) and between tests that need a clean slate mid-run. `POST
/api/users/companies` is idempotent per `(user_id, canonical_source_key)`, so
leftover rows would otherwise silently change what a LATER test in the same
run observes (e.g. AC-11's "no second row" claim is only meaningful starting
from zero owned companies).

Handles the one shape a naive sweep misses (PLAN.md §8): a row stuck in
`health_state='discovering'` deletes the same way as any other row through
`DELETE /api/users/companies/{id}` — `remove_owned_company` doesn't
special-case health_state, it only checks ownership — so no separate branch
is needed for it here. The still-queued `custom_discovery` procrastinate job
for a company that no longer exists is handled at the DB layer instead: the
e2e stack owns its OWN Procrastinate broker and `ensure_db.sh` truncates
`procrastinate_jobs` on every `stack_up.sh` run (not just first clone), so a
wedged job from a killed run can never survive into the next one.
"""

from __future__ import annotations

import httpx


def list_owned_company_ids(base_url: str, token: str, *, timeout: float = 15.0) -> list[str]:
    resp = httpx.get(
        f"{base_url}/api/users/companies",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return [c["id"] for c in resp.json()["companies"]]


def sweep(base_url: str, token: str, *, timeout: float = 30.0) -> int:
    """Delete every company `token`'s user owns. Returns how many were removed."""
    removed = 0
    # Loop rather than a single pass: a delete is one company at a time and
    # nothing else is racing this connection, but looping until the list is
    # empty is cheap insurance against any surprise (e.g. a company that
    # briefly 500s and needs a retry).
    for _ in range(2):
        ids = list_owned_company_ids(base_url, token, timeout=timeout)
        if not ids:
            break
        for company_id in ids:
            resp = httpx.delete(
                f"{base_url}/api/users/companies/{company_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )
            if resp.status_code not in (204, 404):
                raise RuntimeError(
                    f"reset_user.sweep: DELETE {company_id} returned "
                    f"{resp.status_code}: {resp.text}"
                )
            removed += 1
    return removed


def assert_clean(base_url: str, token: str, *, timeout: float = 30.0) -> None:
    sweep(base_url, token, timeout=timeout)
    remaining = list_owned_company_ids(base_url, token, timeout=timeout)
    if remaining:
        raise AssertionError(
            f"reset_user.assert_clean: {len(remaining)} companies still owned "
            f"after sweep: {remaining}"
        )


if __name__ == "__main__":
    # Run as `python -m e2e.shared.db.reset_user [base_url]` from the repo
    # root so the relative package import below resolves.
    import sys

    from ..auth.mint import OTHER_USER, PRIMARY_USER, mint_token

    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8201"
    for user in (PRIMARY_USER, OTHER_USER):
        tok = mint_token(user)
        n = sweep(base, tok)
        print(f"reset_user: swept {n} companies for {user['email']}")
