# fake job-enricher (e2e fixture)

Not an enricher. This tree stands in for the live enricher checkout in the
`enricher-cutover` e2e section (`e2e/enricher-cutover/PLAN.md` §2). The section
commits it as the "old prod" git repo and as `src/enricher` of a fake JVN remote,
so its tree hash is what the cutover matches.

It honours exactly the contract the cutover relies on:

- `data/enricher.db` (WAL, `user_version` 3) with `ticks`, `meta`, `stage_timings`
  and `enrichments`;
- the enricher's own `"<pid>|<iso>"` O_EXCL tick lock, with `lock.py`'s rules (a live
  holder blocks, a dead one blocks until 3 h, a pre-boot lock is reclaimed);
- `cli tick-acquire` exits 75 while the lock is held;
- `cli health` prints one JSON object with volatile keys (`now`, `*_at`, `*_age_s`);
- `scripts/enrich_tick_wrapper.sh` follows the real wrapper's lock protocol.

How long a tick runs and how it closes come from `$FAKE_CONTROL` (`OLD_*` / `NEW_*`
lines), read on every poll, so a test can wedge or fail one checkout at a time.
