"""CO-REAL — the REAL prod tag as the old prod.

The tree the cutover will move on the real machine (``git archive
enricher-prod-eeff1c9:src/enricher``, or ``$E2E_CUTOVER_REAL_TAG``) becomes the
old prod, with a real ``cli init`` database. Phases A-D run the REAL ``uv sync
--frozen`` (venv equivalence: same Python, same installed packages) and the REAL
``cli health`` equivalence; launchd is stubbed and the first tick is faked
(``fixtures/stubs/real_first_tick.sh``: the real CLI's tick-acquire/tick-end,
no pull, no model). It needs the tag: a missing tag FAILS with the fix — it is
never skipped.
"""

from __future__ import annotations

import os
import re
import subprocess

import pytest

import cutover_sandbox as cs

REAL_TAG = os.environ.get("E2E_CUTOVER_REAL_TAG", "enricher-prod-eeff1c9")


def test_coreal_prod_tag_tree_cuts_over(make_sandbox, step, host):
    step(f"looking up tag {REAL_TAG} in this checkout")
    cp = subprocess.run([host.git, "-C", str(cs.REPO_ROOT), "rev-parse", "--verify", "--quiet",
                         f"refs/tags/{REAL_TAG}^{{commit}}"], capture_output=True, text=True)
    if cp.returncode != 0:
        pytest.fail(
            f"tag {REAL_TAG} is not in this checkout, so CO-REAL cannot build the real old prod. "
            "Fix: `git fetch --tags origin` (CI: actions/checkout needs `fetch-depth: 0`, and the "
            f"tag must be pushed: `git push origin {REAL_TAG}`).", pytrace=False)

    step("building the old prod from the real tag tree (real uv sync, real cli init)")
    sb = make_sandbox(real_tag=REAL_TAG,
                      extra_env={"FAKE_JOB_OVERRIDE": str(cs.STUBS / "real_first_tick.sh")})
    want_tree = subprocess.run([host.git, "-C", str(cs.REPO_ROOT), "rev-parse",
                                f"{REAL_TAG}:src/enricher"], capture_output=True,
                               text=True).stdout.strip()
    assert sb.old_tree == want_tree

    step("running the cutover")
    cp = sb.run_cutover("--run", label="real tag tree")
    assert cp.returncode == 0, sb.output()
    st = sb.state()
    assert st["phase"] == "DONE", sb.output()

    step("the ref is the tag; the new prod's src/enricher IS the tag's tree")
    assert (st["ref"], st["ref_source"]) == (REAL_TAG, "tag")
    assert sb.git(sb.new, "rev-parse", "HEAD:src/enricher").strip() == want_tree

    step("real uv sync gave an equivalent venv; real cli health was identical")
    m = re.search(r"venv equivalent: python (3\.12\.\d+), (\d+) packages identical", cp.stdout)
    assert m and int(m.group(2)) >= 10, sb.output()
    assert "`cli health` identical in both checkouts" in cp.stdout
    assert (sb.new_enricher / ".env.local").read_bytes() == (sb.old / ".env.local").read_bytes()

    step("the faked first tick went through the real CLI and closed ok")
    first = st["first_tick"]
    assert first["status"] == "ok" and first["id"] > (st["copied_max_tick_id"] or 0), first
    assert sb.loaded_program() == str(sb.new_enricher / cs.WRAPPER_REL)
    texts = sb.texts()
    assert len(texts) == 1 and "DONE" in texts[0] and REAL_TAG in texts[0], texts
