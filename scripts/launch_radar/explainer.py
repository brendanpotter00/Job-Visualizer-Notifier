"""Example request bodies for the public "How Launch Radar works" page.

The page shows the exact JSON each step sends to Parallel. It reads them from
``src/frontend/src/pages/LaunchRadarHowItWorksPage/requestBodies.json``, which is
this module's output: the loop's own request builders, called with example inputs.
``tests/unit/test_launch_radar_explainer.py`` fails when the two drift apart.
Regenerate the file from the repository root with:

    cd scripts && python -m launch_radar.explainer > ../src/frontend/src/pages/LaunchRadarHowItWorksPage/requestBodies.json
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

from launch_radar import backfill, leaders, monitors, research, resolve

# The examples the page uses: one company per step, the same ones the page's copy names.
BACKFILL_WINDOW = ("2026-09-07", "2026-10-07")
BACKFILL_GENERATOR, BACKFILL_LIMIT = "base", 20
WEBSITE_EXAMPLE = ("finmid", "finmid raises EUR 17M Series A extension")
COMPANY, DOMAIN = "Raindrop AI", "raindrop.ai"
COMPANY_CONTEXT = "Raindrop AI announced a $35M Series A"
LEADER = SimpleNamespace(name="Zubin Singh Koticha", description="CEO and Co-Founder", url=None)


def example_request_bodies() -> dict[str, Any]:
    """Each diagram step's request body, keyed by the page's step id."""
    return {
        "monitor": monitors.create_request("series_a_plus"),
        "backfillFind": backfill.create_request(*BACKFILL_WINDOW, BACKFILL_GENERATOR, BACKFILL_LIMIT),
        "backfillEnrich": backfill.enrich_request(*BACKFILL_WINDOW),
        "website": resolve.search_request(*WEBSITE_EXAMPLE),
        "leaders": leaders.findall_request(COMPANY, DOMAIN),
        "company": research.brief_request(COMPANY, DOMAIN, COMPANY_CONTEXT),
        "team": research.team_request(COMPANY, DOMAIN),
        # leaders.add_pedigree_runs sends exactly these two fields.
        "leaderResearch": {
            "inputs": leaders.pedigree_inputs([LEADER], COMPANY, DOMAIN),
            "default_task_spec": leaders.pedigree_spec(),
        },
    }


if __name__ == "__main__":
    json.dump(example_request_bodies(), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
