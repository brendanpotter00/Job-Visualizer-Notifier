"""Summarise job-count drift across replay rounds.

The GO criterion is not "the recipe ran once". It is "the recipe still
returns the same jobs days later with no agent involved". This reads every
results/*.json and reports, per target, the count each round and the worst
drift against the first successful round.
"""

from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).parent / "results"

DRIFT_TOLERANCE = 0.05  # GO criterion: within 5% across all replays


def main() -> None:
    rounds: list[tuple[str, dict[str, dict]]] = []
    for path in sorted(RESULTS.glob("*.json")):
        payload = json.loads(path.read_text())
        label = payload.get("label", path.stem)
        if label in ("smoke", "discover"):
            continue  # authoring noise, not measurement rounds
        by_target = {r["target"]: r for r in payload["results"]}
        rounds.append((f"{label} @ {payload.get('utc', '?')}", by_target))

    if not rounds:
        print("no measurement rounds yet (run ./replay_round.sh replay-1)")
        return

    targets = sorted({t for _, by_target in rounds for t in by_target})
    width = max(len(t) for t in targets) + 2

    print(f"{'target':<{width}}" + "".join(f"{label:>26}" for label, _ in rounds) + "   verdict")
    for target in targets:
        cells = []
        counts = []
        for _, by_target in rounds:
            result = by_target.get(target)
            if result is None:
                cells.append(f"{'-':>26}")
            elif result["ok"]:
                cells.append(f"{result['job_count']:>26}")
                counts.append(result["job_count"])
            else:
                cells.append(f"{'RAISED':>26}")
        if not counts:
            verdict = "NO SUCCESSFUL RUN"
        elif len(counts) < len(rounds):
            verdict = "FAILED A ROUND"
        else:
            baseline = counts[0]
            worst = max(abs(c - baseline) / baseline for c in counts) if baseline else 1.0
            verdict = f"drift {worst * 100:.1f}%" + ("  OK" if worst <= DRIFT_TOLERANCE else "  OVER 5%")
        print(f"{target:<{width}}" + "".join(cells) + f"   {verdict}")

    print(
        f"\n{len(rounds)} round(s) recorded. GO needs >=3 rounds spanning >=48h "
        f"with drift <= {DRIFT_TOLERANCE:.0%}."
    )


if __name__ == "__main__":
    main()
