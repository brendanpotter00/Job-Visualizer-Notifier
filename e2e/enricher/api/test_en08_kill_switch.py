"""EN-08 — JVN's kill switch.

``ENRICHMENT_USE_EXTERNAL=false`` is how the operator turns the laptop off
from the server side without touching the laptop: ``/pending`` hands out
nothing (and says ``enabled: false``), so no row is ever claimed. Everything
else keeps working — notably ``/metrics``, so the dashboard still sees the
laptop is alive.

Needs a second, short-lived backend with the flag flipped (:8206, same
database), the add-companies AC-09 pattern. The sandbox points at it through
the environment for this one fire (``JVN_BASE_URL`` beats ``.env.local``).
"""

from __future__ import annotations

import pytest

import fixtures
from conftest import KILLSWITCH_PORT, second_backend, seed

GROUP = fixtures.EN08


@pytest.mark.slow
def test_en08_with_the_flag_off_a_tick_claims_nothing_and_touches_no_row(sandbox, stub, db_conn, step, case_dir):
    step("seeding EN-08")
    seed.reseed(GROUP)

    step(f"starting the kill-switch backend on :{KILLSWITCH_PORT} (ENRICHMENT_USE_EXTERNAL=false)")
    with second_backend(KILLSWITCH_PORT, {"ENRICHMENT_USE_EXTERNAL": "false"},
                        case_dir / "killswitch-backend.log") as url:
        step("firing one tick against it")
        run = sandbox.fire(extra_env={"JVN_BASE_URL": url}, label="tick-killswitch")
    assert run.rc == 0, f"see {run.log_path}"
    run.expect("provider is DISABLED", "the enricher did not report the kill switch")

    step("the tick claimed nothing and still closed ok")
    (tick,) = sandbox.ticks()
    assert tick["status"] == "ok"
    assert (tick["claimed"], tick["classified"], tick["sent"]) == (0, 0, 0), tick
    assert stub.chats() == [], "no row was claimed, so no model call may happen"

    step("no JVN row was touched")
    rows = seed.listings(db_conn)
    assert set(rows) == {j.job_id for j in GROUP}
    for jid, row in rows.items():
        assert row["enrichment_status"] is None and row["enrichment_claimed_at"] is None, (jid, row)
    assert seed.enrichments(db_conn) == {}

    step("the metrics push is NOT gated — JVN still heard from the laptop")
    (jvn_tick,) = seed.ticks(db_conn)
    assert jvn_tick["status"] == "ok" and jvn_tick["claimed"] == 0, jvn_tick
