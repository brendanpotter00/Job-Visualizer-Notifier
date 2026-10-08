# Launch Radar: the rest of the team counts toward Talent

**Today** Talent is `scoring.score_talent(leaders)` only: top school +8 (cap 24), top employer +10 (cap 30), prior
exit +15 (cap 30), 10+ years +5 (cap 10), weighted by pedigree confidence (high 1.0 / medium 0.8 / low 0.5 / unknown 0.8),
null when no leader has people data, ceiling **94**. The team tally (`team_stats`, Task `pro`) is display only.
**Decided by the user:** Talent = up to 50 from the leaders + up to 50 from the team, plus a free `radar.sh rescore`.

## 1. Formula (`scripts/launch_radar/scoring.py`)

`half_up(x) = floor(x + 0.5)` everywhere (Python `round` is banker's rounding and would make 0.5 cases unexplainable).

**Leaders part, 0–50.** `leaders_raw, talent_reasons = score_talent(leaders)` exactly as today (0–94, int).
`talent_leaders = half_up(leaders_raw * 50 / LEADERS_MAX)` with `LEADERS_MAX = sum(caps) = 94` computed from
`TALENT_RUBRIC`, never hard-coded. Null when `leaders_raw` is null. A plain rescale (not new caps), so the stored
legacy Talent number converts exactly (§3).

**Team part, 0–50** = `score_team(team_stats) -> (int | None, reasons)`. Let `n = profiles_found`.
- `school_hits = min(n, Σ count of schools[] entries matching TALENT_RUBRIC.top_school names)`; the same match
  (`_match_any`, same lists) on `prior_employers[]` with `top_employer` names gives `employer_hits`. The tally is
  per school/employer, so a person with two top schools counts twice; capping the sum at `n` keeps the share ≤ 1.
- `school_share = school_hits / n`, `employer_share = employer_hits / n`. Shares, not headcount: 15 of 33 beats 21 of 140.
- Points: `school = 15 × min(1, school_share / 0.5)`, `employer = 20 × min(1, employer_share / 0.5)` (full points at
  half the found profiles; profiles with no listed background are in the denominator, so linear-to-100% would cap
  real teams near a third of the points), `exits = 0 / 10 / 15` for `ex_founders_with_exit` 0 / 1 / ≥2 (an absolute
  count: exits are rare and one already matters). Weights mirror the leader caps (school < employer ≈ exit).
- Small sample: `× min(1, n / 5)` on the whole part (3 profiles count 60%; 1 counts 20%).
- Confidence: the pipeline discards the tally's basis (`team, _ = self._wait(...)` in `pipeline.py`) and the card
  never stored it, so there is no confidence to apply: weight **1.0** (documented; the share cap and shrinkage are the
  tempering). Storing the tally basis is out of scope.
- `talent_team = half_up((school + employer + exits) × shrink)`.
- **Null** (part missing, not 0): `team_stats` null, `profiles_found` null or 0, or both `schools` and
  `prior_employers` empty (the tally found people but no background: unknown, not "no top talent"). An empty tally on
  only one side scores that side 0 and says so in a reason line.

**Revised after review** (supersedes the bullets above where they differ; CONTRACT §6.6 is authoritative):
- The tally lists entries, not people (BrainChild: 59 school entries for 42 profiles), so the share is
  `hits / max(n, listed)` per side, not `min(n, hits) / n`; reason lines say what was counted
  (`15 of the 48 schools listed across 33 profiles are top schools (+9)`).
- Each component is rounded once and the part is the sum of the shown integers (Composio read +8 +6 +10 under a 25).
- A side with nothing listed is missing, not 0: the other side and the exits are scaled up to 50.
- The small-sample shrink pulls toward the leaders' part, not 0: `n/5 × raw + (1 − n/5) × L` (Cleavr's one stray
  profile no longer halves its Talent); with no leaders' part it pulls toward 0, stated in the reason line.

**Blend** (`blend_talent(L, T) -> (talent, basis)`):
- both present → `talent = L + T`, `talent_basis = "both"`;
- one present → `talent = 2 × present`, basis `"leaders"` / `"team"`. Missing data is not evidence of a weak team,
  so it is never scored as 0; the card is ranked on what is known, and the basis + UI say "doubled, no team data";
- both null → `talent = null` (dash), `talent_basis = null`.

**Reasons.** `talent_reasons` keeps today's leader lines unchanged. New `talent_team_reasons`, e.g.
`top schools on 15 of 33 profiles (+14)`, `top employers on 9 of 33 profiles (+11)`, `1 ex-founder with an exit (+10)`,
`only 3 profiles found: counts at 60%`, `no school data in the tally`, or for a null part
`no public profiles found for the rest of the team` / `the team tally lists no schools or employers`.

## 2. Payload / API / UI

`scores` gains four fields; all optional with defaults so the stored cards, `cards-2026-10-07.json` and its import
validate unchanged:
```
talent: int|None (0–100, the blend)       talent_leaders: int|None = None (0–50)
talent_team: int|None = None (0–50)       talent_basis: Literal["leaders","team","both"]|None = None
talent_reasons: list[str]  (leaders)      talent_team_reasons: list[str] = []
```
`talent_basis = None` with a non-null `talent` means **legacy** (pre-blend: `talent` is the raw leader score).
Backend `LaunchRadarScores` (`models.py`) adds them plus an `after` validator: basis None ⇒ both parts None; "both" ⇒
both set and `talent == L+T`; "leaders"/"team" ⇒ that part set, the other None, `talent == 2×part`. So the breakdown
on a card always adds up. camelCase on the wire: `talentLeaders`, `talentTeam`, `talentBasis`, `talentTeamReasons`.
Sort by Talent is unchanged (`scores.talent`).

`GET /api/internal/launch-radar/cards` gains `all=true` (explicit opt-in, still keyset paged) for `rescore --all`; and
its `missing_talent` filter changes to "the **leaders part** is null" (`talent_leaders` null on a blended card, `talent`
null on a legacy one), because `refresh --missing-talent` exists to find cards with no leader data, and a team-only
card now has a non-null Talent.

Frontend (`launchRadarTypes.ts`, `CardBody.tsx` `WhyTheseScores`): the card keeps its single Talent `ScoreBadge`. In
"Why these scores" the Talent bullet becomes `Talent 72: leaders 37 + team 35 (each out of 50)` (or
`leaders 19 of 50, doubled: no team data`) with two sub-bullets `Leaders 37: <talentReasons>` /
`Team 35: <talentTeamReasons>` (a null part shows its reason). A legacy card (basis null, talent set) renders today's line.

## 3. `radar.sh rescore` (free; `scripts/launch_radar/rescore.py`)

`radar.py rescore (--domains d1,d2 | --all) [--dry-run]` — every live status (new, saved, archived; it costs
nothing). `load_config(need_parallel=False)`; `deps.make_client` is never called (a test injects one that raises);
no `start_run`, no reserve (PUT needs no run). Reads cards through `BackendClient.cards(domains=… | all_cards=True)`
(paged by `after_id`). Per card:
- **Leaders part is carried, not recomputed**: the card does not store the pedigree confidence (`build_leader` keeps it
  only in the score input; `founded_before` is a display string, `founded_raw` is gone), so `score_talent` cannot be
  re-run on a stored card. It doesn't need to be: rescore never changes leader inputs, and the legacy `talent` IS
  today's exact `leaders_raw` (int ≤ 94). Rule: `talent_basis` set → `L = talent_leaders`; else (legacy)
  `L = leaders_part(talent)`. `talent_reasons` carried. So unchanged inputs reproduce today's leader points exactly.
- Team part from the stored `team_stats`; blend; **VC recomputed** with `score_vc` from the stored `funding`
  (`{latest_round, prior_rounds: [{investors: ", ".join(lead + other)}]}`): verified to reproduce score **and** reasons
  on all 28 local cards.
- `event.announced_at` normalized with `card.announced_on` (as `refresh` does) so an old card never 422s.
- PUT only when `scores` changed; second run is a no-op. Log `company: talent 70→72 (leaders 37 + team 35), vc 100→100`,
  then `rescore: changed N, unchanged M, gone G, errors E`. A 404 (`CardGone`) is counted, not fatal; any other
  `BackendError` → exit 1 after the summary. `--dry-run` prints the same lines and PUTs nothing.

The pipeline and `refresh` produce the same fields via one function `talent_scores(leader_inputs, team_stats)` in
`build_payload` (which now scores from the built `team_stats`). **Bug fixed on the way:** `refreshed_payload` calls
`build_payload(team=None)` and pastes `team_stats` back afterwards, which would score a refreshed card without its
team; it now passes `team=old["team_stats"]` (`build_team_stats` is idempotent on its own output; tested).

Run locally after implementation: `radar.sh rescore --all --dry-run`, then `rescore --all` against :8000
(`jvn_launch_radar`, the one write this plan makes there). The user runs the same against production after importing.

## 4. Preview: the 28 local cards (scratch computation, nothing written)

| Company | Old | Leaders /50 | Team /50 | New | Rank old→new | Team inputs (top-school / top-employer hits of n, exits) |
|---|---|---|---|---|---|---|
| Lightfield | 70 | 37 | 35 | 72 | 1→1 | 15/33, 9/33, 1 |
| OneByZero (archived) | 48 | 26 | — | 52 | 2→2 | 0 profiles → leaders ×2 |
| BrainChild Bio | 46 | 24 | 15 | 39 | 3→3 | 21/42, 0/42, 0 |
| SignSplit | 35 | 19 | — | 38 | 5→4 | 0 profiles → leaders ×2 |
| Composio | 22 | 12 | 25 | 37 | 14→5 | 7/25, 4/25, 1 |
| Melius | 34 | 18 | 12 | 30 | 6→6 | 1/6, 1/6, 0 |
| StepFun | 32 | 17 | 13 | 30 | 7→7 | 5/18, 2/18, 0 |
| Bluecore Energy | 12 | 6 | 22 | 28 | 19→8 | 1/5, 2/5, 0 |
| Firi | 24 | 13 | 14 | 27 | 11→9 | 1/3, 1/3, 0 (×0.6) |
| Blee | 4 | 2 | 22 | 24 | 27→10 | 7/15, 3/15, 0 |
| EUCLYD | 40 | 21 | 0 | 21 | 4→11 | 0/9 (no schools listed), 0/9, 0 |
| Veridue | 23 | 12 | 9 | 21 | 12→12 | 2/3, 0/3, 0 (×0.6) |
| Poseidon Aerospace | 18 | 10 | 8 | 18 | 18→13 | 5/23, 1/23, 0 |
| Procuros | 26 | 14 | 4 | 18 | 10→14 | 0/42, 4/42, 0 |
| Navana.ai | 21 | 11 | 6 | 17 | 15→15 | 1/19, 2/19, 0 |
| Graph AI Services | 31 | 16 | 0 | 16 | 8→16 | 0/8, 0/8, 0 |
| Gaia Dynamics | 22 | 12 | 2 | 14 | 13→17 | 1/14, 0/14, 0 |
| Solstice Oncology | 26 | 14 | 0 | 14 | 9→18 | 0/4, 0/4, 0 (×0.8) |
| Cato | 0 | 0 | 12 | 12 | 28→19 | 1/13, 0/13, 1 |
| Comparables.ai | 4 | 2 | 9 | 11 | 24→20 | 0/9, 2/9, 0 |
| Euno | 20 | 11 | 0 | 11 | 16→21 | 0/24, 0/24, 0 |
| Get Mika | 20 | 11 | 0 | 11 | 17→22 | 0/10, 0/10, 0 |
| Hope Care | 4 | 2 | 6 | 8 | 26→23 | 3/16, 0/16, 0 |
| Outline | 8 | 4 | — | 8 | 22→24 | tally lists no background → leaders ×2 |
| Jaipur Robotics | 10 | 5 | 3 | 8 | 21→25 | 1/12, 0/12, 0 |
| finmid | 10 | 5 | 1 | 6 | 20→26 | 1/52, 0/52, 0 |
| Guardrail (archived) | 8 | 4 | 0 | 4 | 23→27 | 0/5, 0/5, 0 |
| Cleavr | 4 | 2 | 0 | 2 | 25→28 | 0/1, 0/1, 0 (×0.2) |

Flags: (a) **OneByZero / SignSplit** keep top-4 ranks on leaders alone (×2) because the tally found 0 profiles; the
alternative (missing team = 0) would drop them to 26 / 19. (b) The name lists are US-tech-centric, so biotech /
semiconductor / European teams (Solstice, Graph AI, EUCLYD, Euno, Mika) score team 0 and fall 6–8 places; same bias as
the leader rubric, now applied twice. (c) Small samples move a lot even shrunk: Bluecore (5 profiles) 19→8.
(d) Substring match counts "Harvard Business School Online" (Hope Care) as top school. (e) Big risers look right:
Blee 27→10 (7 of 15 top schools, AWS ×3), Composio 14→5 (IIT/Stanford/MIT, Databricks/Google, an exit).

## 5. Files and tests

- `scripts/launch_radar/scoring.py`: `LEADERS_MAX`, `half_up`, `leaders_part`, `score_team`, `blend_talent`,
  `talent_scores`, `rescored_scores(payload)` (§3 rule). `card.py`: `build_payload` uses `talent_scores`.
  `refresh.py`: pass the old tally into `build_payload`. New `rescore.py`. `radar.py`: `rescore` subcommand + docstring.
  `backend_client.py`: `cards(all_cards=True)`. `schemas.py`: drop "never scored" from the TEAM_SCHEMA comment.
- Backend: `models.py` (`LaunchRadarScores` fields + validator), `routers/internal_launch_radar.py` (`all`),
  `services/launch_radar.py` (`find_cards` `all` + leaders-part `missing_talent` SQL).
- Frontend: `features/admin/launchRadarTypes.ts`, `pages/AdminLaunchRadarPage/components/CardBody.tsx`
  (+ a pure `talentBreakdown` helper in `format.ts`), test fixtures.
- Docs: `CONTRACT.md` §4 payload + TS type, §6.2 commands, §6.6 (delete "the team tally never feeds a score"),
  refresh section; `scripts/launch_radar/README.md` (cost table "display only", new Rescoring section);
  `src/backend/CLAUDE.md` Launch Radar bullet (`GET /cards` `all`, `missing_talent` meaning, scores fields);
  local `parallel-reference.html` Scoring section (+ "display only" rows at lines ~106/171/245).
- Tests (scripts, `scripts/tests/unit/`): `test_launch_radar_scoring.py` — leaders rescale (94→50, 70→37, 0→0, null),
  share cap with multi-school sums, 0.5 saturation, exits 0/1/2+, shrink n<5, every null rule, blend + basis,
  half-up, reason text; `test_launch_radar_card.py` — payload carries the six talent fields and passes the backend
  model; build_team_stats idempotent; `test_launch_radar_refresh.py` — refreshed card's Talent includes the team;
  new `test_launch_radar_rescore.py` — legacy→blended (exact leader carry), blended card is a no-op (no PUT),
  VC reproduced, dry-run PUTs nothing, CardGone counted, paged `--all`, Parallel client never built;
  `test_launch_radar_cli.py` — parser (`--domains`/`--all` exclusive, required); `test_launch_radar_backend_client.py`
  — `all=true` param and paging. Backend: `test_internal_launch_radar.py` — legacy payload still validates, blended
  payload round-trips, inconsistent basis/sum 422, `all=true`, `missing_talent` on legacy vs blended vs team-only
  cards; `test_launch_radar_admin.py` — camelCase fields. Frontend: `RadarCard.test.tsx` — breakdown lines for
  both / leaders-only / team-only / legacy, single badge number unchanged.

## Revised: team exits removed

The user: "We're checking the leaders for [prior exits and ex-founders], not the team." So the team part has no exits
component (CONTRACT §6.6 is authoritative):
- `TEAM_SCHEMA` and the tally request no longer ask for `ex_founders_with_exit`, and `build_team_stats` no longer writes
  it. An older payload that still carries it validates (backend `LaunchRadarTeamStats`: optional, excluded from every
  dump, so it is not re-stored or sent to the page), and scoring and the UI ignore it.
- Team part = schools 25 + employers 25 (was 15 + 20 + exits 0/10/15), same share math (`hits / max(n, listed)`, full
  points at a share of one half), each side rounded once and summed. A side with nothing listed is still missing, not 0:
  the other side is scaled to the full 50 (`s = 50 / 25`). The small-sample rule is unchanged (`n/5 × raw + (1 − n/5) × L`).
- Leaders keep the exit signal unchanged (prior founder with an exit +15, cap 30).
- The card's Rest of team section has no prior-exit line; it says "No schools or employers listed" when both are empty.
- The §4 preview table above predates this revision and its team numbers are stale; `radar.sh rescore --all` recomputes
  every stored card for $0.

## Removed: add-company PR step

The user: "Remove the step entirely." The loop opened add-company PRs (#333, #334) on its own; both were closed. The run
now only researches and posts cards, and tracking a company is a human call from the admin page:
- Gone: `scripts/launch_radar/pr_step.py` and its tests, the two `radar.py` subcommands that listed PR candidates and
  recorded a PR on a card, their `BackendClient` methods, the matching internal routes and service functions, and the
  skill's PR section. The headless allowlist (`wrapper.sh`, quoted in SKILL.md §0) is now `Read(./**)` plus the exact
  `radar.sh` commands: no Edit, Write, Agent, web tools, `git` or `gh`.
- The free ATS board check stays (it powers "Job board" and "Already tracked"); its `pr_ready` helper is now
  `ats.board_has_jobs`, and new payloads no longer carry `pr_ready`. An older payload that does still validates
  (backend `LaunchRadarPayload.pr_ready`: optional, excluded from every dump), like `ex_founders_with_exit` above.
- `launch_radar_cards.pr_url` is kept as a legacy, unused column (no migration); only the tombstone still clears it. The
  admin response no longer carries `prUrl` or `prReady`, and the frontend types dropped both.
