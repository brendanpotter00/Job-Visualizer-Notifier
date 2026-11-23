# /north-star-once — one headless north-star-loop run

Headless one-shot for `scripts/north_star_loop/wrapper.sh` (LaunchAgent `com.bp.jvn-north-star-loop`). The wrapper has already run `loop.py sync` and `loop.py next`, and passes the action as the argument: `propose`, `build N`, or `readout N`. Interactively, invoke the `north-star-loop` skill instead.

Action: $ARGUMENTS

**Exit discipline (a hung session holds the lock until the wrapper's 90-minute cap):**

- Do NOT call `ScheduleWakeup`, `/loop`, or the `Skill` tool. Read the skill file directly.
- Do NOT use `run_in_background: true`, spawn detached work, or poll with `sleep` loops. Subagents are allowed only if you wait for them in-turn.
- The skill's §4 heartbeat line is the FINAL step. After the status block, end the turn.

## Procedure

1. Read `.claude/skills/north-star-loop/SKILL.md` relative to the checkout you were launched in. Read it in full.
2. Run the mode named by the action above, end to end, obeying §0 exactly.
3. Write the §4 heartbeat line and end the turn.
