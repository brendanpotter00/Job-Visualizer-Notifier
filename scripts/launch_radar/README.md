# Launch Radar loop — runbook

Finds startups that just announced a round or a launch, researches each one with the
Parallel API, and posts one card per company to the admin page `/admin/launch-radar`.
It never opens a PR or changes the repo: whether to track a company is decided by a
human, from the admin page.

The procedure lives in `.claude/skills/launch-radar/SKILL.md`; this directory is the
Python loop plus the launchd shell around it. The design is in
`docs/implementations/launch-radar/` (`CONTRACT.md` §6 is the loop).

## Pieces

| Path | Role |
|---|---|
| `radar.sh` | The only entry point. Loads the env file into its own process, then runs `python -m scripts.launch_radar.radar` under `uv` with `parallel-web` and `httpx` |
| `radar.py` | CLI: `monitors-ensure`, `run`, `backfill`, `monitors-cancel`, `heartbeat`, `import`, `refresh`, `rescore` |
| `pipeline.py` | One `run` invocation (see [One run](#one-run)) and the per-company research |
| `backfill.py` | The one-off `backfill` sweep (see [Backfill](#backfill-the-past-month-once)) |
| `refresh.py` | `refresh`: re-research cards that have no leaders (see [Refreshing cards](#refreshing-cards-with-no-leaders)) |
| `rescore.py` | `rescore`: recompute stored cards' scores for free (see [Rescoring](#rescoring-cards-free)) |
| `export_cards.py` · `importer.py` | Move researched cards to another backend with no Parallel calls (see [Moving local cards](#moving-local-cards-to-production)) |
| `monitors.py` · `resolve.py` · `leaders.py` · `research.py` · `ats.py` · `scoring.py` · `card.py` · `schemas.py` · `domains.py` | One concern each (see the module docstrings) |
| `backend_client.py` | The backend's internal routes (`/api/internal/launch-radar/*`, `X-Internal-Key`) |
| `state.py` | Resumable local state: `queue.json`, `companies/<domain>.json`, `backfill.json`, `refresh/<domain>.json`, `refresh_done.json`, `heartbeat.log` |
| `wrapper.sh` | launchd entry: 90-min cap, process-group kill, single-flight lock, heartbeat check (exit 97 if it did not advance, 98 if the skill recorded `status=error`), `--allowedTools` allowlist |
| `com.bp.jvn-launch-radar.plist.template` · `install_launch_agent.sh` | The daily 19:00 LaunchAgent |
| `.claude/commands/launch-radar-once.md` | The headless shim the wrapper runs (`claude -p /launch-radar-once`) |

## How spend is capped

Every billed Parallel call is reserved first with `POST /runs/{uuid}/reserve`. The
backend ledger (`launch_radar_spend`) refuses with 402 past the run's `--budget` (default
$1.00, at most $5) or the global cap (`LAUNCH_RADAR_SPEND_CAP_USD`, default **$5.00**, set
only on the backend). Monitor executions are billed by Parallel on their own schedule, so
each run records them as accrued spend, and when less than $0.10 of the cap is left the
loop **cancels the Monitors** and stops.

| step | Parallel call | price |
|---|---|---|
| Monitors | 3 × `event_stream` on `base` (`seed`, `series_a_plus`, `launch`), daily | $0.01 each per day |
| domain lookup | Search API, `mode="advanced"` (Search's default, best-ranked mode), per event without a domain (at most 10 per run) | $0.005 |
| leaders | FindAll, generator `preview`, `match_limit` 8 | $0.10 |
| brief | Task run on `core` (website, ATS, funding, `founders`) | $0.025 |
| team tally | Task run on `pro` (Talent's team half, see [Scoring](#scoring)) | $0.10 |
| pedigree | Task Group, one `base` run per leader | $0.01 × leaders |

One company costs $0.225 plus $0.01 per leader (at most 8), so $0.225-0.305. The ATS board
check uses the free public Greenhouse/Ashby/Lever APIs.

## One run

`radar.sh run [--max-companies 3] [--budget 1.00] [--exclude d1,d2] [--deadline-s 540] [--dry-run]`

1. `POST /runs`, then accrue each Monitor's executions since its `charged_through`. Over
   the cap (or under $0.10 left): cancel every Monitor and exit 2.
2. Read each active Monitor's events newer than its cursor (free).
3. **Domain lookup** (`resolve.py`): an event without `company_domain` gets one Search API
   call, reserved first, and keeps the top result whose host carries the company name
   (news, directory and social hosts are skipped). A 402 here exits 2 before the cursors
   move, so the events are read again next run.
4. **Dedupe, before any spend:** one card per normalized domain, ever. Big tech,
   `--exclude`, domains already queued, and `GET /seen` hits (a card exists, or the name
   is already tracked) are skipped. Survivors go to `queue.json`; then the cursors move.
5. **Research**, 3 at a time: every resumed company, plus up to `--max-companies` new ones
   (queued Monitor events before backfill items; a Monitor event with no progress for 3
   days is dropped, a backfill item never is). Per company:
   1. Reserve and create FindAll, the brief and the team tally together.
   2. FindAll's matched candidates that pass `is_person` (a name of two or more words,
      not a company page), at most 8, are the leaders. When it keeps **zero**, the
      leaders come from the brief's `founders` (deduped by name, at most 8; a profile
      URL is kept only when it is a LinkedIn link), and the card says
      `leaders from the brief (FindAll found none)` under its issues.
   3. Pedigree: reserve, create one Task Group, and add one `base` run per leader in a
      single `add_runs`. That attempt is recorded before the call; after an ambiguous
      failure the group is asked first, and only a group holding no runs gets them again
      (under a `#retryN` reservation).
   4. Wait for the brief and the team tally, check the job board, score (deterministic:
      founding a company counts only with an exit; Talent blends the leaders and the team,
      see [Scoring](#scoring)),
      then `POST /cards`. A 409 is a skip.
6. `POST /runs/{uuid}/finish`.

`--dry-run` reads events and `GET /seen` only: no billed call, no backend write, no local
write.

## Setup on the always-on server laptop

1. **Checkout + tools.** Clone the repo where launchd should run it, check out `main`,
   and install `uv` (`brew install uv`; `radar.sh` finds it on the LaunchAgent's `PATH`,
   `/opt/homebrew/bin` or `/usr/local/bin`) and the Claude Code CLI (`claude`, logged in).
2. **Secrets file**, readable only by you:

   ```sh
   mkdir -p ~/.config/jvn-launch-radar
   install -m 600 /dev/null ~/.config/jvn-launch-radar/env
   ${EDITOR:-vi} ~/.config/jvn-launch-radar/env
   ```

   ```sh
   BACKEND_URL=https://<railway backend host>    # the backend directly, never the Vercel proxy
   INTERNAL_API_KEY=<the backend's INTERNAL_API_KEY>
   PARALLEL_API_KEY=<parallel key>
   ```

   **Do not** export `PARALLEL_API_KEY` (or the internal key) from that laptop's
   `~/.zshrc`. Only `radar.sh` should ever have them, so Claude's own Bash never sees
   them. Leave `LAUNCH_RADAR_STATE_DIR` unset: the wrapper checks the heartbeat in the
   default `~/Library/Application Support/jvn-launch-radar/`.
3. **Smoke test, free:**

   ```sh
   scripts/launch_radar/radar.sh rescore --all --dry-run   # backend reachable + key accepted; writes nothing
   scripts/launch_radar/radar.sh run --dry-run      # reads events and /seen; spends nothing
   ```

4. **Create the Monitors** ($0.03, reserved first): `scripts/launch_radar/radar.sh monitors-ensure`.
5. **Headless test of the whole skill** (the same command launchd runs):

   ```sh
   PROJECT_DIR="$PWD" CLAUDE_BIN="$(command -v claude)" sh scripts/launch_radar/wrapper.sh
   tail -3 "$HOME/Library/Application Support/jvn-launch-radar/heartbeat.log"
   ```

6. **Install the LaunchAgent** (daily 19:00): `sh scripts/launch_radar/install_launch_agent.sh`
   (add `--claude-bin /path/to/claude` if `claude` is not on `PATH`).

## Backfill: the past month, once

Monitors only report events that happen after they are created (their own backfill is a
small sample, all dated the day they were created). `backfill` fills that gap once:

```sh
scripts/launch_radar/radar.sh backfill --dry-run     # prints both requests and the estimate; calls nothing
scripts/launch_radar/radar.sh backfill               # --days 30 --limit 20 --generator base
scripts/launch_radar/radar.sh run --max-companies 5  # researches what it queued (repeat until the queue is empty)
```

Flags: `--days` 1-90 (30), `--limit` 5-100 (20; at most 10 with `preview`), `--generator`
`preview|base|core` (`base`), `--exclude`, `--deadline-s` (540), `--dry-run`, `--new`.

1. **One FindAll run** (`entity_type="companies"`, `match_limit = --limit`): early-stage startups,
   not big tech or public companies, that announced a newly closed pre-seed to Series B round or a notable product
   launch between `today - --days` and today (UTC; the concrete dates are written into the conditions).
2. **One enrichment** on `base` turns each match into a Monitor-shaped event (`company_name`, `company_domain`,
   `event_type`, `round`, `amount_usd`, `investors`, `announced_at`, `source_url`, `headline`). Rows dated outside
   the window are dropped; numbers are cast (`15000000.0` becomes `$15M`). A domain that is a news or directory
   site falls back to the match's own URL, then to the Search lookup `run` uses.
3. **Same path as `run`:** domain lookup, dedupe, then `queue.json`. The card's event block carries `source_url`,
   `announced_at`, round and amount, with `origin: "findall_backfill"`.

| step | price | reserved before the call |
|---|---|---|
| FindAll `base` | $0.25 + $0.03 per match | $0.25 + $0.03 × `--limit` ($0.85 at 20) |
| enrichment `base` | $0.01 per match | $0.01 × matches |
| domain lookups | $0.005 each | one row each |

So 20 matches cost $1.15 at most (the backfill's own backend run budget), plus $0.225-0.305 per company `run` later
researches, all against the same $5 cap. A reservation above $1 is split into rows of $1 (the backend's limit per row).

**Resume, never pay twice.** `$STATE_DIR/backfill.json` holds the FindAll id, every reservation and the progress.
Re-running `backfill` after a crash, a 402 (exit 2) or the deadline (exit 3) resumes polling the saved run with its
saved settings: no second create, no second enrichment. A finished backfill is not re-run; `--new` starts (and pays
for) a fresh sweep. Delete `backfill.json` only to abandon a run that can never finish.

## Refreshing cards with no leaders

FindAll `preview` evaluates only 5-10 candidates, so for some companies it confirms nobody
(or only company pages, which `is_person` drops). Cards posted before the brief-founders
fallback existed have no leaders and so no leaders' half of Talent; `refresh` applies the
fallback to them:

```sh
scripts/launch_radar/radar.sh refresh --missing-talent --dry-run      # lists the cards and the estimate; free
scripts/launch_radar/radar.sh refresh --missing-talent --budget 1.20  # or: --domains a.ai,b.io
```

Per card it buys only a new brief (`core`, $0.025) and, if the brief names founders, their
pedigree ($0.01 each), each reserved first under one backend run; then it rescores and
`PUT`s the payload (`/api/internal/launch-radar/cards/{id}/payload`). The status,
`posted_at`, event, team tally (scored again as Talent's team half) and job board stay; a
card whose new brief fails is left as it was. `--missing-talent` selects new and saved cards
whose leaders' half of Talent is null (`talent_leaders`, or `talent` on a pre-blend card); an
archived card is refreshed only with `--include-archived`, and a card that already has
leaders is skipped. All briefs are created up front, so they research in parallel.

Resume works like `run`: exit 2 on a 402, exit 3 at the deadline; re-run the same command and
the saved ids in `$STATE_DIR/refresh/<domain>.json` are reused, never re-created or
re-reserved. A finished card goes into `$STATE_DIR/refresh_done.json` and is never selected
again (remove its entry there to pay for another refresh).

## Scoring

Deterministic (`scoring.py`, CONTRACT §6.6). **VC** (0-100) comes from the brief's rounds.
**Talent** (0-100) is a 50/50 blend, `half_up` rounding (`floor(x + 0.5)`) throughout:

- **Leaders, 0-50**: the leader rubric (top school +8 cap 24, top employer +10 cap 30, prior
  exit +15 cap 30, 10+ years +5 cap 10, weighted by pedigree confidence: high 1.0, medium
  0.8, low 0.5) scores 0-94, rescaled `× 50 / 94`. Null when no leader has people data.
- **Team, 0-50** from the `team_stats` tally of `n = profiles_found` non-founders. The tally
  lists schools and employers, not people, so each side's share is its top-list entries over
  `max(n, entries listed on that side)`. Top schools give `25 × min(1, share / 0.5)` and top
  employers `25 × min(1, share / 0.5)` (shares, not headcount; full points at one half). No
  prior exits: those are checked on the leaders, not the team, so the tally does not ask for
  them and an older card's `ex_founders_with_exit` is ignored. Each side is rounded once and the
  part is their sum, so the `(+x)` lines add up. A side with nothing listed is missing, not 0:
  the other side is scaled up to 50. With fewer than 5 profiles the part counts
  `n / 5` and the rest follows the leaders' part (1 profile: 20% team, 80% leaders), so a
  stray profile never halves a card. Weight 1.0 (the tally's confidence is not kept). Null
  with no tally, `n` null or 0, or neither side listing anything.
- **Blend**: both parts → their sum (`talent_basis` `both`); one part → that part doubled
  (`leaders` / `team`: missing data is not a weak team); neither → null.

`scores` stores `talent`, `talent_leaders`, `talent_team`, `talent_basis`, `talent_reasons`
(the leaders) and `talent_team_reasons`. A card with `talent_basis` null and a `talent` is a
pre-blend card whose `talent` is the raw 0-94 leader score; `rescore` converts it. A lone
part is rounded before it is doubled, so a leaders-only card can sit 1 above `raw × 100 / 94`
(accepted: it keeps the validated `talent == 2 × part`).

## AI Talent grade (free)

The rule blend above counts a fixed list of names. After each run posts its cards, the nightly
skill has **one Claude subagent per new card** grade Talent against
`.claude/skills/launch-radar-grade/rubric.md`: leaders 0-40, industry fit 0-25, team density
relative to the team's size 0-25, track record 0-10. The grade becomes the card's Talent; the
rule score is kept as `talent_rules` and is the fallback when a grade is missing or invalid.
No Parallel call is made. Procedure, prompts and the backtest: the `launch-radar-grade` skill.

```sh
scripts/launch_radar/radar.sh grade-export --ungraded --dir .launch-radar-grades   # or --all / --domains
# ... one subagent per .launch-radar-grades/inputs/<id>.json writes .launch-radar-grades/grades/<id>.json
scripts/launch_radar/radar.sh grade-apply --dir .launch-radar-grades --dry-run     # validate + print; then without --dry-run
```

`rescore` keeps a grade; `refresh` drops it (new leaders), so the next night re-grades the card.

## Rescoring cards (free)

`rescore` recomputes the scores of existing cards from what each card already stores. It
makes **no Parallel call**, opens no backend run and reserves nothing:

```sh
scripts/launch_radar/radar.sh rescore --all --dry-run    # prints "company: talent 70→67 (leaders 37 + team 30), vc 100→100"
scripts/launch_radar/radar.sh rescore --all              # or: --domains a.ai,b.io
```

Every live card (new, saved, archived) is read through `GET /cards?all=true` (paged). The
leaders' half is **carried**, not recomputed (the card does not keep the pedigree confidence):
`talent_leaders` on a blended card, or a pre-blend card's raw `talent` rescaled exactly. The
team half is scored from `team_stats`, and VC from the stored `funding`. A card is `PUT`
(`/cards/{id}/payload`; status and `posted_at` stay) only when its `scores` changed, so a
second run is a no-op; the event date is normalized on the way. A deleted card (404) is
counted; any other backend error is counted and the command exits 1 after the summary
line `rescore: changed N, unchanged M, gone G, errors E`. After importing cards into
production, run the same command with production's env file to convert them. Do not run
`rescore` while a `refresh` is running: its `PUT` replaces the whole payload, so it would
undo the refresh's new leaders.

## Moving local cards to production

Cards researched against a local backend (database `jvn_launch_radar`) can be copied to
production without paying for the research again. The import posts each stored payload
through the same `POST /cards` the loop uses, makes **no Parallel call** and reserves
nothing (each payload's `cost_usd` already records what it cost).

1. **On the laptop that did the research**, export every card that is not deleted:

   ```sh
   uv run scripts/launch_radar/export_cards.py   # [--out PATH] [--source LABEL]; DATABASE_URL defaults to the local jvn_launch_radar
   ```

   It writes `docs/implementations/launch-radar/data/cards-<YYYY-MM-DD>.json` (format
   `launch-radar-cards/v1`, oldest first) and prints the count by status. Commit that file
   (it holds the researched founders' names and profile links).
2. **After the PR is merged and deployed** (Railway runs the Alembic migrations on boot),
   on the server laptop, whose env file points `BACKEND_URL` at production:

   ```sh
   git pull
   scripts/launch_radar/radar.sh import --file docs/implementations/launch-radar/data/cards-<date>.json --dry-run
   scripts/launch_radar/radar.sh import --file docs/implementations/launch-radar/data/cards-<date>.json
   ```

   `--dry-run` checks the whole file and asks `GET /seen` which cards production already
   has; it posts nothing. The real import opens and finishes one backend run (`import`)
   and prints `imported · skipped as duplicate · failed`.
3. **Re-running is safe.** A card production already has is a 409 and is skipped. Any
   other error stops the import with exit 1 after the summary of what got in; fix the
   cause and run the same command again.

The whole file is validated before the first POST (format tag, a live status, a payload
whose `domain` is the card's), and production re-validates every payload. The internal API
creates every card as **new** and stamps `posted_at` with the import time, so a card that
was saved or archived on the laptop is listed in the import's output: re-save or
re-archive it on `/admin/launch-radar`. Deleted cards are not exported, so production does
not remember them; a later run there could research such a domain again.

## Ops

```sh
launchctl kickstart gui/$(id -u)/com.bp.jvn-launch-radar     # fire now
launchctl print gui/$(id -u)/com.bp.jvn-launch-radar         # status + next fire
sh scripts/launch_radar/install_launch_agent.sh --uninstall  # remove the agent
tail -f ~/Library/Logs/jvn-launch-radar.log                  # watch a run
tail -5 "$HOME/Library/Application Support/jvn-launch-radar/heartbeat.log"
scripts/launch_radar/radar.sh monitors-cancel                # stop all Monitor spend (free); confirms each
```

`radar.sh` exit codes: `0` done · `1` error · `2` stopped on the budget · `3` incomplete
(state is saved under `companies/<domain>.json`; the next `run` resumes and never
re-creates a saved step). Exit 3 also covers a transient error (HTTP 429/5xx, a dropped
connection) while collecting a paid-for result or checking the job board: the company
keeps its state and is retried, and only after 6 such invocations is its card posted
with the gap listed under "Research incomplete". A create call that failed in a way
that may still have reached Parallel is reserved again under a `#retryN` step, so the
ledger over-counts a possible double charge rather than missing it.

To pause the radar without losing anything: `monitors-cancel`, then uninstall the agent.
`monitors-ensure` creates fresh Monitors later.

## Design notes

- **Untrusted input.** Monitor events, search results, FindAll candidates and Task outputs
  are web research. The loop copies only known fields, clips text, keeps only http(s) URLs
  and plain board tokens, and never acts on their content. The skill's §0 says the same
  for Claude.
- **No permission skipping.** The wrapper runs `claude` with an explicit
  `--allowedTools` allowlist (one `ALLOWED_TOOLS` block in `wrapper.sh`).
  It never uses `--dangerously-skip-permissions`;
  `tests/unit/test_launch_radar_wrapper.py` fails if that changes. Every Bash entry is
  an exact `radar.sh` command; there is no generic `git`, `gh`, `curl`, `python`, `pip`
  or `npm` entry (each can run code or upload a local file), and no Edit, Write, Agent
  or web tool. File reads are scoped to the checkout.
- **No PRs.** The run used to turn one verified card a day into an add-company PR. That
  step was removed after it opened PRs on its own: tracking a company is a human call.
  The `launch_radar_cards.pr_url` column it wrote is kept (no migration) but unused.
- **Dedupe.** `POST /cards` returns 409 for a domain already posted (in any status,
  deleted cards included), which the loop logs as a skip.
- **Tests.** `cd scripts && pytest tests/unit -k launch_radar` — the Parallel SDK and the
  backend are faked (`tests/unit/launch_radar_fakes.py`); nothing touches the network.
