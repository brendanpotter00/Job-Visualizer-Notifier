"""Roll the per-target measurements up into the table the spike report needs."""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).parent


def main() -> None:
    rounds = sorted(BASE.glob("results/replay-1-*.json"))
    latest = json.loads(rounds[-1].read_text()) if rounds else {"results": []}
    by_target = {r["target"]: r for r in latest["results"]}

    print(f"{'target':<13}{'kind':<11}{'jobs':>6}{'replay_s':>10}{'capture_s':>11}  {'total_path':<12}{'min_jobs':>9}")
    for recipe_path in sorted(BASE.glob("recipes/*.json")):
        recipe = json.loads(recipe_path.read_text())
        target = recipe.get("target", recipe_path.stem)
        capture = BASE / "captures" / target / "report.json"
        capture_seconds = json.loads(capture.read_text()).get("wall_seconds") if capture.exists() else "-"
        result = by_target.get(target, {})
        print(
            f"{target:<13}{recipe['kind']:<11}"
            f"{str(result.get('job_count', '-')):>6}"
            f"{str(result.get('seconds', '-')):>10}"
            f"{str(capture_seconds):>11}  "
            f"{str(recipe.get('total_path') or '-'):<12}"
            f"{str(recipe.get('expected_min_jobs')):>9}"
        )


if __name__ == "__main__":
    main()
