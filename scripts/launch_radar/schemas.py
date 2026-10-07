"""Parallel request schemas, Monitor queries and price tables.

Copied from the POC (``scripts/launch_radar_poc/poc.py`` and ``team_stats.py``)
with one change: ``BRIEF_SCHEMA.ats`` gains a required ``board_url``.
Prices are USD from parallel-docs ``raw/getting-started/pricing.md``.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Pricing (USD)
# ---------------------------------------------------------------------------
MONITOR_PRICE = {"lite": 0.003, "base": 0.010}  # per execution (check)
TASK_PRICE = {"lite": 0.005, "base": 0.010, "core": 0.025, "core2x": 0.050, "pro": 0.100}
FINDALL_PRICE = {  # (fixed, per_match)
    "preview": (0.10, 0.00),
    "base": (0.25, 0.03),
    "core": (2.00, 0.15),
    "pro": (10.00, 1.00),
}
ENTITY_SEARCH_PRICE = 0.005


def ceil_cost(x: float) -> float:
    """Round an estimate UP to the next tenth of a cent."""
    return math.ceil(round(x * 1000, 6)) / 1000


# ---------------------------------------------------------------------------
# Monitors: three narrow event_stream queries (CONTRACT §6.4)
# ---------------------------------------------------------------------------
MONITOR_PROCESSOR = "base"
MONITOR_FREQUENCY = "1d"
MONITOR_QUERIES: dict[str, str] = {
    "seed": (
        "Startups announcing a newly closed pre-seed or seed venture funding round, as reported in "
        "press releases or tech/business news. One specific company per event."
    ),
    "series_a_plus": (
        "Startups announcing a newly closed Series A, Series B or later venture funding round, as "
        "reported in press releases or tech/business news. One specific company per event."
    ),
    "launch": (
        "Notable new product launches by early-stage AI and software startups, as reported in press "
        "releases or tech/business news. One specific company per event."
    ),
}

MONITOR_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "company_name": {"type": "string", "description": "Name of the company the event is about."},
        "company_domain": {
            "type": ["string", "null"],
            "description": "Company's primary website domain, e.g. example.com (no scheme, no path). null if unknown.",
        },
        "event_type": {
            "type": "string",
            "enum": ["funding", "launch"],
            "description": "funding = a closed venture round; launch = a notable new product launch.",
        },
        "round": {
            "type": ["string", "null"],
            "description": "Funding stage, e.g. Seed, Series A, Series B. null for launches.",
        },
        "amount_usd": {
            "type": ["string", "null"],
            "description": "Round size in USD as written, e.g. '$15M'. null if not a funding event or undisclosed.",
        },
        "investors": {
            "type": ["string", "null"],
            "description": "Comma-separated investors, lead investor(s) first. null if none named.",
        },
        "announced_at": {
            "type": ["string", "null"],
            "description": "Date the news was announced, YYYY-MM-DD. null if unknown.",
        },
        "source_url": {"type": "string", "description": "URL of the article or press release reporting the event."},
        "headline": {"type": "string", "description": "One-line headline summarizing the event."},
    },
    "required": [
        "company_name",
        "company_domain",
        "event_type",
        "round",
        "amount_usd",
        "investors",
        "announced_at",
        "source_url",
        "headline",
    ],
    "additionalProperties": False,
}

# Leader pedigree: one Task Group run per leader (processor base).
PEDIGREE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "current_title": {"type": "string", "description": "The person's current title at the company."},
        "linkedin_url": {"type": ["string", "null"], "description": "LinkedIn profile URL. null if not found."},
        "education": {
            "type": "array",
            "description": "Degrees / schools attended (university level). Empty if none found.",
            "items": {
                "type": "object",
                "properties": {
                    "school": {"type": "string", "description": "University name."},
                    "degree": {"type": ["string", "null"], "description": "e.g. BS, MS, PhD, MBA; null if unknown."},
                    "field": {"type": ["string", "null"], "description": "Field of study; null if unknown."},
                    "grad_year": {"type": ["string", "null"], "description": "YYYY; null if unknown."},
                },
                "required": ["school", "degree", "field", "grad_year"],
                "additionalProperties": False,
            },
        },
        "prior_roles": {
            "type": "array",
            "description": "Prior employers BEFORE the current company, most recent first.",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Employer name."},
                    "title": {"type": ["string", "null"], "description": "Role/title; null if unknown."},
                    "years": {"type": ["string", "null"], "description": "e.g. '2019-2022'; null if unknown."},
                },
                "required": ["company", "title", "years"],
                "additionalProperties": False,
            },
        },
        "founded_before": {
            "type": "array",
            "description": "Companies this person founded or co-founded BEFORE the current one. Empty if none.",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name."},
                    "outcome": {
                        "type": "string",
                        "enum": ["acquired", "ipo", "shut_down", "operating", "unknown"],
                        "description": "What happened to that company.",
                    },
                    "acquirer": {"type": ["string", "null"], "description": "Acquirer if acquired, else null."},
                    "exit_year": {"type": ["string", "null"], "description": "YYYY of exit, else null."},
                },
                "required": ["company", "outcome", "acquirer", "exit_year"],
                "additionalProperties": False,
            },
        },
        "years_experience": {
            "type": ["string", "null"],
            "description": "Approximate total years of professional experience as an integer string, e.g. '12'.",
        },
        "industry_experience_summary": {
            "type": "string",
            "description": "1-2 sentences on the person's domain / industry experience.",
        },
        "notable_signals": {
            "type": "array",
            "description": "Short notable facts (awards, notable projects, publications, prior exits). Empty if none.",
            "items": {"type": "string"},
        },
    },
    "required": [
        "current_title", "linkedin_url", "education", "prior_roles", "founded_before",
        "years_experience", "industry_experience_summary", "notable_signals",
    ],
    "additionalProperties": False,
}

# Company brief: one Task run on core.
ATS_ENUM = ["greenhouse", "ashby", "lever", "gem", "workday", "eightfold", "other", "none"]
BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "one_liner": {"type": "string", "description": "One sentence: what the company is."},
        "website_url": {"type": "string", "description": "The company's official homepage URL, e.g. https://www.example.com."},
        "what_they_do": {"type": "string", "description": "2-4 sentences on product, customers and market."},
        "latest_round": {
            "type": "object",
            "description": "The company's most recent announced priced funding round.",
            "properties": {
                "stage": {"type": ["string", "null"], "description": "e.g. Seed, Series A; null if none found."},
                "amount_usd": {"type": ["string", "null"], "description": "Round size as written, e.g. '$15M'."},
                "announced_at": {"type": ["string", "null"], "description": "YYYY-MM-DD (or YYYY-MM)."},
                "lead_investors": {"type": "array", "items": {"type": "string"},
                                   "description": "Lead investor firms/people."},
                "other_investors": {"type": "array", "items": {"type": "string"},
                                    "description": "Other participating investors."},
            },
            "required": ["stage", "amount_usd", "announced_at", "lead_investors", "other_investors"],
            "additionalProperties": False,
        },
        "prior_rounds": {
            "type": "array",
            "description": "Earlier rounds, most recent first. Empty if none.",
            "items": {
                "type": "object",
                "properties": {
                    "stage": {"type": "string", "description": "e.g. Pre-seed, Seed."},
                    "amount_usd": {"type": ["string", "null"], "description": "As written, e.g. '$4M'."},
                    "announced_at": {"type": ["string", "null"], "description": "YYYY-MM-DD or YYYY-MM."},
                    "investors": {"type": "string", "description": "Comma-separated investors, leads first."},
                },
                "required": ["stage", "amount_usd", "announced_at", "investors"],
                "additionalProperties": False,
            },
        },
        "total_raised_usd": {"type": ["string", "null"], "description": "Total disclosed funding, e.g. '$30M'."},
        "latest_announcement": {
            "type": "object",
            "description": "The company's most recent major announcement (funding or launch).",
            "properties": {
                "headline": {"type": "string", "description": "One-line headline."},
                "url": {"type": ["string", "null"], "description": "URL of the press release or article."},
                "announced_at": {"type": ["string", "null"], "description": "YYYY-MM-DD."},
                "kind": {"type": "string", "enum": ["funding", "launch", "other"], "description": "Type."},
            },
            "required": ["headline", "url", "announced_at", "kind"],
            "additionalProperties": False,
        },
        "notable_facts": {"type": "array", "items": {"type": "string"},
                          "description": "3-6 short impressive / differentiating facts."},
        "blurb": {
            "type": "string",
            "description": "2-3 sentences for a job seeker focused on the team's talent, the funding rounds "
                           "and the single most impressive thing about the company.",
        },
        "careers_url": {"type": ["string", "null"], "description": "Careers / jobs page URL. null if none."},
        "ats": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ATS_ENUM,
                    "description": "Applicant tracking system hosting the public job board. Infer from job "
                                   "posting URLs: boards.greenhouse.io/<token> or job-boards.greenhouse.io/<token> "
                                   "=greenhouse; jobs.ashbyhq.com/<token>=ashby; jobs.lever.co/<token>=lever; "
                                   "jobs.gem.com/<token>=gem; *.myworkdayjobs.com=workday; *.eightfold.ai=eightfold.",
                },
                "board_token": {
                    "type": ["string", "null"],
                    "description": "The board token / slug from the job board URL (the <token> part). null if none.",
                },
                "board_url": {
                    "type": ["string", "null"],
                    "description": "The public job board URL (where the openings are listed). null if none.",
                },
            },
            "required": ["provider", "board_token", "board_url"],
            "additionalProperties": False,
        },
    },
    "required": [
        "one_liner", "website_url", "what_they_do", "latest_round", "prior_rounds", "total_raised_usd",
        "latest_announcement", "notable_facts", "blurb", "careers_url", "ats",
    ],
    "additionalProperties": False,
}

# Team tally (non-founders): one Task run on pro. Display only, never scored.
TALLY = {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["name", "count"], "additionalProperties": False}}

TEAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "profiles_found": {"type": "integer", "description":
                           "How many current non-founder employees you found public profiles for."},
        "team_size_estimate": {"type": "string", "description": "Approximate total headcount, e.g. '20-30'."},
        "schools": {**TALLY, "description":
                    "Universities attended by those employees, with how many attended each. Most common first."},
        "prior_employers": {**TALLY, "description":
                            "Notable previous employers of those employees, with counts. Most common first."},
        "ex_founders_with_exit": {"type": "integer", "description":
                                  "How many of them previously founded a company that was acquired or IPO'd."},
        "sample_names": {"type": "array", "items": {"type": "string"}, "description":
                         "Names of the employees counted (at most 25), so the tally can be checked."},
    },
    "required": ["profiles_found", "team_size_estimate", "schools", "prior_employers",
                 "ex_founders_with_exit", "sample_names"],
    "additionalProperties": False,
}
