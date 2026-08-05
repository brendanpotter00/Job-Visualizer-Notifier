# /health-watch-once — one headless scraper-health-watch run

Headless one-shot for the LaunchAgent at
`~/Library/LaunchAgents/com.bp.jvn-health-watch.plist` (spawned via
`scripts/health_watch/wrapper.sh`). Not for interactive use — interactively,
invoke the `scraper-health-watch` skill instead. Cadence is owned by launchd,
so this command does NOT call `ScheduleWakeup`.

**Headless exit discipline (load-bearing — a hung session blocks the LaunchAgent
and its 90-min wrapper timeout is the only backstop):**

- Do NOT call `ScheduleWakeup`, `/loop`, or the `Skill` tool. Read the skill
  file directly (below) instead of invoking it.
- Do NOT use `run_in_background: true` on any Bash call — every command runs in
  the foreground and returns before the next step.
- Do NOT spawn detached background work. The one sanctioned Agent call is the
  research subagent in the skill's §6, and you must wait for it in-turn.
- Do NOT poll with `while … sleep …` loops. If a foreground Bash call hits its
  tool-side timeout, Read the output file once and move on.
- The skill's §10 heartbeat line is the FINAL step. After printing the status
  block, end the turn immediately — no follow-up tool calls.

## Procedure

1. Read `/Users/bpotter/developer/personal/Job-Visualizer-Notifier/.claude/skills/scraper-health-watch/SKILL.md`
   in full.
2. Execute its `daily` mode end-to-end: §2 checks → §3 classify → §4 dedupe →
   §5 probes → §6 research (only if needed) → §7 fix build (only if needed) →
   §8 PR → §9 text → §10 heartbeat + status block.
3. Obey the skill's §0 hard rules exactly (prod read-only, never merge, ≤1 fix
   PR, ≤3 texts, no attribution footers).
4. End the turn.
