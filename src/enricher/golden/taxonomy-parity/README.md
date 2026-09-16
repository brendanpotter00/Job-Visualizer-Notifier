# JVN taxonomy parity snapshot

`jvn_facets.json` is **JVN's `src/backend/taxonomy.json` (SCHEMA-15's artifact)**,
alongside `jvn_facets.sha256` recording its sha256.

**Never re-derive the slug list here.** Typing the 17 slugs into this repo by
hand is exactly the seam SCHEMA-15 exists to close: two independently-typed
lists agree right up until one of them is edited. `tests/test_cross_repo_parity.py`
carries a guard for this (`test_the_vendored_snapshot_is_the_jvn_artifact_not_a_rederived_list`)
— the artifact also carries `levels`, a key this repo never writes.

## ⚠ RIGHT NOW THIS COPY IS A FORECAST, NOT A COPY

The 15 → 17 widening (`growth_engineering`, `product_engineering`) landed in
**this** repo first. JVN's `src/backend/taxonomy.json` still carries **15**
slugs, so a verbatim copy of it would fail half (a) — and not on two rows but on
**eleven**: the two missing slugs plus the nine `sort_order` values that shifted
when the new slugs were **inserted** at 8 and 12 rather than appended.

So the file in the tree was regenerated **locally**, byte-for-byte in the shape
`src/backend/tools/generate_taxonomy_artifact.py` emits
(`json.dumps(..., indent=2)`, `sort_order == enumerate(sorted(slugs))`), with the
two new rows added. Everything else — `categories`, `levels`,
`subcategory_sources` — is still JVN's bytes, untouched.

**What this costs:** until the re-copy below, half (a) cannot catch drift in the
subcategory slug list itself; it still catches every other kind (a category
added or dropped, a level renamed, a `subcategory_sources` change, a
`parent_slug` change, a hand-edit of the file).

**THE ONE ACTION:** the moment JVN's PR-B re-emits `taxonomy.json` with 17 slugs,
run the `git show` recipe below and restore the provenance table. Delete this
whole section when you do — a stale "forecast" note is how a real divergence
gets waved through.

## Provenance

| | |
|---|---|
| source repo | `Job-Visualizer-Notifier` |
| source path | `src/backend/taxonomy.json` |
| source ref | `origin/feat/swe-subcat-b-backend` (PR-B) |
| source commit | `b1356ca446b555f4e74f9257b19e1ad49a8c696b` — *"SCHEMA-15: taxonomy.json, the generator, and the JVN half of the cross-repo parity check"* |
| blob | `a4d917f2b1d741a6bd11912c7be1ed1a22ec3d28` |
| sha256 of that verbatim copy | `0b51da538684458742ed492ac23473cf265fa2d5dcc5cead5e78db0020897461` |
| **local delta on top** | subcategories re-emitted at **17** slugs (see the section above) |
| sha256 of the file in the tree | `d22600096b10a8424da05f7d732811b39bd945c9fe3bbcf87925459dad3dcc05` |

⚠ **PR-B is not merged yet.** Refresh this copy (and the rows above) once it
lands on JVN `main`, and again any time SCHEMA-15's generator re-emits the file.

## Refreshing

Offline, straight from the JVN git object — this is the copy the PR-blocking
half (a) compares against:

```sh
JVN=~/developer/personal/Job-Visualizer-Notifier
REF=origin/feat/swe-subcat-b-backend    # -> origin/main once PR-B merges
git -C "$JVN" show "$REF:src/backend/taxonomy.json" > golden/taxonomy-parity/jvn_facets.json
shasum -a 256 golden/taxonomy-parity/jvn_facets.json \
  | sed 's#golden/taxonomy-parity/##' > golden/taxonomy-parity/jvn_facets.sha256
```

Live, from a running JVN (half (b) — also refreshes the snapshot):

```sh
uv run python -m job_enricher.cli parity-check --base-url <JVN> --write-snapshot
```

`--write-snapshot` writes **both** files itself, so there is no second command
to forget. It also **refuses to write** in the two cases that would damage this
artifact:

- the parity check **failed** — overwriting the vendored copy with diverged live
  data is a watchdog erasing the evidence it exists to catch; and
- the live payload carries no `levels` — the result would be a list re-derived in
  this repo, which is exactly what
  `test_the_vendored_snapshot_is_the_jvn_artifact_not_a_rederived_list` rejects.

An unchanged snapshot is left byte-for-byte alone, so the daily launchd run does
not dirty a tracked file (which would abort `deploy.sh` step 3).

⚠ **Refresh BOTH files together**, or the recorded-sha test goes red — the manual
`git show` recipe above is the one that needs the `shasum` line.

## What the tests do if this file is missing

They **FAIL**, loudly. They used to `pytest.skip()`, which meant half (a) — the
PR-blocking, no-network half — reported success while asserting nothing. A
missing snapshot IS the defect; do not turn the assertions back into skips.

Two expected-red windows for the LIVE half (b) are documented in
`docs/RUNBOOK-subcategory-backfill.md`.
