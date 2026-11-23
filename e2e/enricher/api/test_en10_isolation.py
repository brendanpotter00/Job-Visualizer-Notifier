"""EN-10 — isolation and request accounting. Runs LAST (conftest orders it).

Three claims, each proved rather than assumed:

1. **Every model call the enricher made landed on the stub.** The enricher
   prints how many chunks it queued (``classify-run: ... chunks=N``,
   ``judge-run: ... chunks=M``); in normal mode each chunk is exactly one call.
   The stub's count must EQUAL N + M — had any call gone to the real ollama on
   :11434 (or anywhere else), the stub would be short. All of them carried
   this section's ``source_id`` and the prod model tag, and nothing but
   ``/api/chat`` was requested.
2. **The enricher's state lives in the sandbox.** Its own interpreter reports
   ``REPO_ROOT`` = the sandbox, and the DB/lock it used are under it.
3. **The dev tree was not touched.** ``src/enricher/data`` in this checkout is
   exactly as ``run.sh`` recorded it before anything ran (absent, today).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import fixtures
from conftest import seed, wrapper_int

GROUP = fixtures.EN10
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _dev_data_state() -> str:
    # The same function run.sh used for the baseline, so the formats match.
    script = (
        'd="$1/src/enricher/data"; if [ -e "$d" ]; then echo present; '
        "find \"$d\" -type f -exec stat -f '%N %z %m' {} + 2>/dev/null | sort; else echo absent; fi"
    )
    return subprocess.run(["bash", "-c", script, "_", str(_REPO_ROOT)],
                          capture_output=True, text=True, check=True).stdout


@pytest.mark.fast
def test_en10_every_model_call_hit_the_stub_and_nothing_left_the_sandbox(sandbox, stub, step):
    step("seeding EN-10 and firing one tick")
    seed.reseed(GROUP)
    run = sandbox.fire()
    assert run.rc == 0, f"see {run.log_path}"

    step("counting the chunks the enricher says it queued")
    classify_chunks = wrapper_int(run.output, "classify-run:", "chunks")
    judge_chunks = wrapper_int(run.output, "judge-run:", "chunks")
    assert classify_chunks == len(GROUP)
    assert judge_chunks == len(fixtures.expected_judged(GROUP)) == 1

    step("comparing with what the stub actually received")
    log = stub.log()
    assert log["count"] == log["chat_count"], f"non-chat requests reached the stub: {log['requests']}"
    assert log["chat_count"] == classify_chunks + judge_chunks, (
        f"the enricher queued {classify_chunks}+{judge_chunks} chunks but the stub saw "
        f"{log['chat_count']} calls — a call went somewhere else, or a chunk retried"
    )
    for req in log["requests"]:
        assert req["source_ids"] == [fixtures.SOURCE_ID], req
        assert req["model"] == fixtures.MODEL, req
        assert req["host"] == "127.0.0.1:8215", req

    step("the enricher's state is under the sandbox")
    assert Path(sandbox.info["repo_root"]).resolve() == sandbox.dir.resolve()
    assert sandbox.db_path.exists() and sandbox.dir.resolve() in sandbox.db_path.resolve().parents
    (tick,) = sandbox.ticks()
    assert tick["status"] == "ok"
    env_local = (sandbox.dir / ".env.local").read_text(encoding="utf-8")
    assert "OLLAMA_BASE_URL=http://127.0.0.1:8215" in env_local
    assert ":11434" not in env_local

    step("the dev tree's data dir is exactly as run.sh found it")
    baseline_file = os.environ.get("E2E_DEV_DATA_BEFORE")
    assert baseline_file and Path(baseline_file).exists(), "run.sh did not record the dev-tree baseline"
    assert _dev_data_state() == Path(baseline_file).read_text(encoding="utf-8"), (
        f"{_REPO_ROOT / 'src/enricher/data'} changed during the run — the sandbox leaked"
    )
