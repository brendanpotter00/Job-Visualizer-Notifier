"""The How it works page shows the exact request bodies the loop sends.

The page reads them from a JSON file in the frontend. This test rebuilds them
with the loop's own request builders and fails if the file is stale; the fix is
to regenerate it (see ``launch_radar/explainer.py``).
"""

import json
from pathlib import Path

from launch_radar import resolve
from launch_radar.explainer import example_request_bodies

ROOT = Path(__file__).resolve().parents[3]
BODIES = ROOT / "src" / "frontend" / "src" / "pages" / "LaunchRadarHowItWorksPage" / "requestBodies.json"


def test_page_request_bodies_match_the_loop():
    on_page = json.loads(BODIES.read_text())
    assert on_page == example_request_bodies(), (
        "requestBodies.json is stale: cd scripts && python -m launch_radar.explainer > "
        "../src/frontend/src/pages/LaunchRadarHowItWorksPage/requestBodies.json"
    )


def test_every_step_has_a_body():
    assert set(example_request_bodies()) == {
        "monitor", "backfillFind", "backfillEnrich", "website", "leaders", "company", "team", "leaderResearch",
    }


def test_search_request_is_what_the_domain_lookup_sends():
    req = resolve.search_request("finmid", "finmid raises EUR 17M Series A extension")
    assert req == {
        "objective": "The official company website (homepage) of the startup finmid. "
                     "Context: finmid raises EUR 17M Series A extension",
        "search_queries": ["finmid official website", "finmid startup"],
        "mode": "advanced",
        "advanced_settings": {"max_results": 8},
    }
