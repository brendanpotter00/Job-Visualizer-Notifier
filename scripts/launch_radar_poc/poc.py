# /// script
# requires-python = ">=3.10"
# dependencies = ["parallel-web>=1.3.5", "httpx"]
# ///
"""Launch Radar proof of concept against the Parallel API.

Subcommands:
  monitor-create   create one event_stream monitor (lite, 30d) for startup funding / launch news
  monitor-events   poll the monitor's events until some arrive (or --max-wait), rank candidates
  monitor-cancel   cancel the monitor and re-retrieve it to confirm status == cancelled
  run-company      full per-company pipeline (FindAll leadership -> enrich pedigree ->
                   Task brief -> free ATS check -> local scoring -> card.json)
  dedupe           normalize domains and filter a candidates JSON against out/seen.json

The API key is read by the SDK from PARALLEL_API_KEY; this script never prints or stores it.
Every Parallel request/response is saved as a JSON fixture; every billable call is checked
against a local budget BEFORE it is made (estimates are rounded up).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
MONITOR_DIR = OUT / "monitor"
SEEN_FILE = OUT / "seen.json"

# ---------------------------------------------------------------------------
# Pricing (USD) from parallel-docs raw/getting-started/pricing.md
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Fixtures / ledger
# ---------------------------------------------------------------------------
def to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def write_json(path: Path, data: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(data), indent=2, default=str) + "\n")
    return str(path)


def read_json(path: Path, default: Any) -> Any:
    """``default`` only when the file does not exist. A corrupt file stops the script:
    silently resetting spend.json would zero the budget ledger, and a lost monitor
    state.json would leave a billing monitor nobody can cancel from here."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"corrupt JSON in {path} ({e}); fix or move it aside by hand - refusing to reset it")


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    """Ordered call log + spend tracker with a hard local budget."""

    def __init__(self, out_dir: Path, budget: float):
        self.out_dir = out_dir
        self.budget = budget
        self.calls_path = out_dir / "calls.json"
        self.spend_path = out_dir / "spend.json"
        self.calls: list[dict] = read_json(self.calls_path, [])
        spend = read_json(self.spend_path, {})
        self.committed: float = float(spend.get("estimated_usd", 0.0))

    def remaining(self) -> float:
        return round(self.budget - self.committed, 6)

    def reserve(self, step: str, est: float) -> float:
        est = ceil_cost(est)
        if est > self.remaining() + 1e-9:
            raise BudgetExceeded(
                f"[budget] refusing {step}: est ${est:.3f} > remaining ${self.remaining():.3f} "
                f"(budget ${self.budget:.2f})"
            )
        self.committed = round(self.committed + est, 6)
        self._save_spend()
        print(f"[budget] {step}: reserved ${est:.3f}; committed ${self.committed:.3f} / ${self.budget:.2f}")
        return est

    def release(self, amount: float) -> None:
        """Give back part of a reservation once the actual cost is known to be lower."""
        self.committed = round(max(0.0, self.committed - amount), 6)
        self._save_spend()

    def log(self, **entry: Any) -> None:
        entry.setdefault("at", now_iso())
        self.calls.append(entry)
        write_json(self.calls_path, self.calls)
        self._save_spend()

    def _save_spend(self) -> None:
        actual = sum(float(c.get("actual_cost_usd") or c.get("est_cost_usd") or 0) for c in self.calls)
        write_json(
            self.spend_path,
            {
                "budget_usd": self.budget,
                "estimated_usd": round(self.committed, 6),
                "actual_estimate_usd": round(actual, 6),
                "remaining_usd": self.remaining(),
                "updated_at": now_iso(),
                "note": "Parallel bills per pricing page; actual_estimate uses real match counts.",
            },
        )


def client():
    from parallel import Parallel

    # max_retries=0: a retried create can duplicate a billed run (no idempotency key).
    return Parallel().with_options(max_retries=0)


# ---------------------------------------------------------------------------
# Domain normalization / dedupe
# ---------------------------------------------------------------------------
def normalize_domain(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in {"", "na", "n/a", "none", "null", "unknown"}:
        return None
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)
    v = v.split("/")[0].split("?")[0].split("#")[0]
    v = v.split("@")[-1].split(":")[0]
    if v.startswith("www."):
        v = v[4:]
    v = v.rstrip(".")
    return v if "." in v else None


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------
MONITOR_QUERY = (
    "Startups announcing a newly closed seed, Series A or later venture funding round, "
    "and notable AI startup product launches, as reported in press releases or tech/business news. "
    "One specific company per event."
)
MONITOR_OUTPUT_SCHEMA = {
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

BIG_TECH = {
    "google.com", "alphabet.com", "apple.com", "microsoft.com", "amazon.com", "aws.amazon.com", "meta.com",
    "facebook.com", "nvidia.com", "openai.com", "anthropic.com", "x.ai", "tesla.com", "ibm.com", "oracle.com",
    "salesforce.com", "intel.com", "amd.com", "netflix.com", "tiktok.com", "bytedance.com", "samsung.com",
    "adobe.com", "uber.com", "deepmind.google", "mistral.ai", "databricks.com",
}


def cmd_monitor_create(args: argparse.Namespace) -> None:
    MONITOR_DIR.mkdir(parents=True, exist_ok=True)
    state = read_json(MONITOR_DIR / "state.json", {})
    if state.get("monitor_id") and state.get("status") != "cancelled" and not args.force_new:
        sys.exit(f"monitor already exists: {state['monitor_id']} (status={state.get('status')}); "
                 "run monitor-cancel first or pass --force-new")
    ledger = Ledger(MONITOR_DIR, args.budget)
    processor, frequency = args.processor, args.frequency
    # The loop runs daily ("1d"). For a one-off test, pass --frequency 30d and cancel after run 1.
    est = ledger.reserve("monitor.create", MONITOR_PRICE[processor] * 1)
    req = {
        "type": "event_stream",
        "frequency": frequency,
        "processor": processor,
        "settings": {
            "query": MONITOR_QUERY,
            "include_backfill": True,
            "output_schema": {"type": "json", "json_schema": MONITOR_OUTPUT_SCHEMA},
        },
        "metadata": {"app": "launch-radar-poc"},
    }
    f_req = write_json(MONITOR_DIR / "01-monitor-create.request.json", req)
    t0 = time.time()
    m = client().monitor.create(**req)
    lat = round(time.time() - t0, 2)
    f_res = write_json(MONITOR_DIR / "01-monitor-create.response.json", m)
    write_json(MONITOR_DIR / "state.json", {"monitor_id": m.monitor_id, "status": m.status,
                                            "created_at": now_iso(), "processor": processor,
                                            "frequency": frequency})
    ledger.log(step="monitor-create", api="Monitor create", sdk_method="client.monitor.create",
               processor=processor, run_id=m.monitor_id, latency_s=lat, est_cost_usd=est,
               fixtures=[f_req, f_res])
    print(f"monitor_id={m.monitor_id} status={m.status} frequency={m.frequency} processor={m.processor}")


def _parse_content(content: Any) -> dict:
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {"text": content}
        except json.JSONDecodeError:
            return {"text": content}
    return content if isinstance(content, dict) else {}


def _rank(ev: dict) -> tuple[int, str]:
    rnd = (ev.get("round") or "").lower()
    score = 0
    if ev.get("event_type") == "funding":
        score = 60
        if "series a" in rnd:
            score = 100
        elif "seed" in rnd:
            score = 80
        elif re.search(r"series [b-z]", rnd):
            score = 70
    elif ev.get("event_type") == "launch":
        score = 50
    return score, ev.get("announced_at") or ""


def cmd_monitor_events(args: argparse.Namespace) -> None:
    from parallel.types import MonitorCompletionEvent, MonitorErrorEvent, MonitorEventStreamEvent

    state = read_json(MONITOR_DIR / "state.json", {})
    mid = args.monitor_id or state.get("monitor_id")
    if not mid:
        sys.exit("no monitor_id (run monitor-create first)")
    c = client()
    ledger = Ledger(MONITOR_DIR, args.budget)
    deadline = time.time() + args.max_wait
    t0 = time.time()
    polls = 0
    all_rows: list[Any] = []
    first_seen_at = None
    while True:
        polls += 1
        rows: list[Any] = []
        cursor = None
        while True:
            kw: dict[str, Any] = {"limit": 100, "include_completions": True}
            if cursor:
                kw["cursor"] = cursor
            page = c.monitor.events(mid, **kw)
            rows.extend(page.events)
            cursor = page.next_cursor
            if not cursor or not page.events:
                break
        all_rows = rows
        n_ev = sum(isinstance(r, MonitorEventStreamEvent) for r in rows)
        n_done = sum(isinstance(r, MonitorCompletionEvent) for r in rows)
        n_err = sum(isinstance(r, MonitorErrorEvent) for r in rows)
        print(f"[poll {polls} @ {int(time.time() - t0)}s] events={n_ev} completions={n_done} errors={n_err}")
        if (n_ev or n_done or n_err) and first_seen_at is None:
            first_seen_at = time.time()
        # after first rows land, wait one more short poll to collect stragglers of the same execution
        if first_seen_at is not None and time.time() - first_seen_at >= args.settle:
            break
        if time.time() > deadline:
            break
        time.sleep(min(args.interval, max(1, deadline - time.time())) if first_seen_at is None else args.settle)
    lat = round((first_seen_at or time.time()) - t0, 2)
    f_raw = write_json(MONITOR_DIR / "02-monitor-events.response.json",
                       {"monitor_id": mid, "fetched_at": now_iso(), "polls": polls, "events": all_rows})
    ledger.log(step="monitor-events", api="Monitor list events", sdk_method="client.monitor.events",
               processor=None, run_id=mid, latency_s=lat, est_cost_usd=0.0, fixtures=[f_raw],
               note="GET is free; latency = seconds from start of polling until first rows were visible")

    candidates = []
    for r in all_rows:
        if not isinstance(r, MonitorEventStreamEvent):
            continue
        content = _parse_content(r.output.content if r.output else None)
        basis = r.output.basis if r.output else []
        confs = {b.field: b.confidence for b in (basis or [])}
        dom = normalize_domain(content.get("company_domain"))
        cand = {
            "name": content.get("company_name"),
            "domain": dom,
            "event_type": content.get("event_type"),
            "round": content.get("round"),
            "amount_usd": content.get("amount_usd"),
            "investors": content.get("investors"),
            "headline": content.get("headline"),
            "source_url": content.get("source_url"),
            "announced_at": content.get("announced_at"),
            "event_id": r.event_id,
            "event_date": r.event_date,
            "confidence": confs,
        }
        if not dom:
            cand["rejected"] = "no domain"
        elif dom in BIG_TECH or any(dom.endswith("." + b) for b in BIG_TECH):
            cand["rejected"] = "big tech / mega-lab"
        candidates.append(cand)
    kept = [c_ for c_ in candidates if "rejected" not in c_]
    kept.sort(key=_rank, reverse=True)
    for i, c_ in enumerate(kept, 1):
        score, _ = _rank(c_)
        c_["rank"] = i
        c_["relevance"] = (
            f"{c_.get('round') or c_.get('event_type')}"
            f"{' ' + c_['amount_usd'] if c_.get('amount_usd') else ''} (rank score {score})"
        )
    f_c = write_json(MONITOR_DIR / "candidates.json", {"kept": kept,
                                                       "rejected": [c_ for c_ in candidates if "rejected" in c_]})
    print(f"wrote {f_c}: {len(kept)} kept, {len(candidates) - len(kept)} rejected")
    for c_ in kept[:10]:
        print(f"  #{c_['rank']} {c_['name']} ({c_['domain']}) {c_['relevance']} | {c_['headline']}")


def cmd_monitor_cancel(args: argparse.Namespace) -> None:
    state = read_json(MONITOR_DIR / "state.json", {})
    mid = args.monitor_id or state.get("monitor_id")
    if not mid:
        sys.exit("no monitor_id to cancel")
    c = client()
    ledger = Ledger(MONITOR_DIR, args.budget)
    t0 = time.time()
    m = c.monitor.cancel(mid)
    lat = round(time.time() - t0, 2)
    f1 = write_json(MONITOR_DIR / "03-monitor-cancel.response.json", m)
    m2 = c.monitor.retrieve(mid)
    f2 = write_json(MONITOR_DIR / "04-monitor-retrieve.response.json", m2)
    state.update({"monitor_id": mid, "status": m2.status, "cancelled_at": now_iso(),
                  "last_run_at": str(m2.last_run_at)})
    write_json(MONITOR_DIR / "state.json", state)
    ledger.log(step="monitor-cancel", api="Monitor cancel + retrieve",
               sdk_method="client.monitor.cancel / client.monitor.retrieve", processor=None, run_id=mid,
               latency_s=lat, est_cost_usd=0.0, fixtures=[f1, f2])
    print(f"monitor_id={mid} cancel->status={m.status} retrieve->status={m2.status} last_run_at={m2.last_run_at}")
    if m2.status != "cancelled":
        sys.exit("monitor NOT cancelled")


# ---------------------------------------------------------------------------
# run-company
# ---------------------------------------------------------------------------
PEDIGREE_SCHEMA = {
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

ATS_ENUM = ["greenhouse", "ashby", "lever", "gem", "workday", "eightfold", "other", "none"]
BRIEF_SCHEMA = {
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
            },
            "required": ["provider", "board_token"],
            "additionalProperties": False,
        },
    },
    "required": [
        "one_liner", "website_url", "what_they_do", "latest_round", "prior_rounds", "total_raised_usd",
        "latest_announcement", "notable_facts", "blurb", "careers_url", "ats",
    ],
    "additionalProperties": False,
}

# ---- scoring rubric (data) -------------------------------------------------
VC_TIERS: dict[str, dict] = {
    "tier1": {
        "lead_points": 60, "participant_points": 45, "extra_points": 10, "extra_cap": 30,
        "names": [
            "Sequoia", "Andreessen Horowitz", "a16z", "Benchmark", "Founders Fund", "Greylock", "Accel",
            "Index Ventures", "Lightspeed", "Kleiner Perkins", "General Catalyst", "Thrive Capital",
            "Khosla Ventures", "Insight Partners", "Coatue", "Tiger Global", "IVP", "Bessemer", "GV",
            "Google Ventures", "Redpoint", "NEA", "New Enterprise Associates", "Conviction", "Kleiner",
        ],
    },
    "tier2": {
        "lead_points": 35, "participant_points": 25, "extra_points": 5, "extra_cap": 15,
        "names": [
            "Felicis", "Initialized", "SV Angel", "First Round", "Craft Ventures", "CRV", "Spark Capital",
            "Menlo Ventures", "Amplify Partners", "Elad Gil", "Nat Friedman", "Daniel Gross", "Box Group",
            "BoxGroup", "Neo", "South Park Commons", "Pear VC", "Abstract Ventures", "Lux Capital",
            "Madrona", "Battery Ventures", "Sapphire", "8VC", "Lerer Hippeau", "Upfront", "Floodgate",
            "Matrix", "Emergence", "Unusual Ventures", "Basis Set", "Gradient", "M12", "NVentures",
            "Salesforce Ventures", "Mayfield", "Costanoa", "Haystack", "XYZ Venture",
        ],
    },
    "yc": {
        "lead_points": 15, "participant_points": 15, "extra_points": 0, "extra_cap": 0,
        "names": ["Y Combinator", "YC"],
    },
}
VC_AMOUNT_BONUS = [(50_000_000, 15), (20_000_000, 10), (10_000_000, 5)]
VC_OTHER_NAMED_POINTS = 10

TALENT_RUBRIC = {
    "top_school": {"points": 8, "cap": 24, "names": [
        "Stanford", "(?-i:MIT)", "Massachusetts Institute of Technology", "Harvard", "Berkeley",
        "Carnegie Mellon", "(?-i:CMU)", "Caltech", "California Institute of Technology", "Princeton", "Yale",
        "Columbia", "Cornell", "University of Pennsylvania", "Wharton", "Oxford", "Cambridge", "ETH Zurich",
        "(?-i:IIT)", "Indian Institute of Technology", "University of Toronto", "Waterloo", "Georgia Tech",
        "Georgia Institute of Technology", "(?-i:UIUC)", "Illinois Urbana", "University of Washington",
        "Tsinghua", "Peking University", "Imperial College", "(?-i:UCLA)", "University of Michigan",
    ]},
    "top_employer": {"points": 10, "cap": 30, "names": [
        "OpenAI", "Anthropic", "DeepMind", "Google", "Meta", "Facebook", "Apple", "Stripe", "SpaceX", "Tesla",
        "Microsoft", "Amazon", "(?-i:AWS)", "Nvidia", "Airbnb", "Uber", "Palantir", "Databricks", "Netflix",
        "Scale AI", "Figma", "Coinbase", "Jane Street", "Two Sigma", "Citadel", "Snowflake", "Datadog",
        "Ramp", "Plaid", "Robinhood", "LinkedIn", "Twitter", "Dropbox", "Instacart", "DoorDash", "Brex",
    ]},
    "prior_exit": {"points": 15, "cap": 30},
    "senior_experience": {"points": 5, "cap": 10, "min_years": 10},
}
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.8, "low": 0.5, None: 0.8}


def _rx(names: list[str]) -> list[tuple[str, re.Pattern]]:
    out = []
    for n in names:
        label = re.sub(r"^\(\?-i:(.*)\)$", r"\1", n)
        out.append((label, re.compile(r"(?<![A-Za-z0-9])" + n + r"(?![A-Za-z0-9])", re.I)))
    return out


def _match_any(text: str, names: list[str]) -> list[str]:
    return [label for label, rx in _rx(names) if rx.search(text or "")]


def parse_usd(s: Any) -> float | None:
    if not s or not isinstance(s, str):
        return None
    m = re.search(r"([\d,.]+)\s*(billion|million|thousand|bn|[bmk])?\b", s.replace("$", ""), re.I)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    mult = {"b": 1e9, "bn": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}.get(unit, 1)
    return v * mult


def score_vc(brief: dict) -> tuple[int, list[str]]:
    reasons: list[str] = []
    lr = brief.get("latest_round") or {}
    leads = [x for x in (lr.get("lead_investors") or []) if x]
    others = [x for x in (lr.get("other_investors") or []) if x]
    for pr in brief.get("prior_rounds") or []:
        others += [x.strip() for x in (pr.get("investors") or "").split(",") if x.strip()]
    best = 0
    extra = 0.0
    hits: dict[str, set[str]] = {}
    for tier, spec in VC_TIERS.items():
        lead_hits = {h for inv in leads for h in _match_any(inv, spec["names"])}
        part_hits = {h for inv in others for h in _match_any(inv, spec["names"])} - lead_hits
        hits[tier] = lead_hits | part_hits
        if lead_hits:
            best = max(best, spec["lead_points"])
            reasons.append(f"vc: {tier} lead investor ({', '.join(sorted(lead_hits))}) -> {spec['lead_points']}")
        if part_hits:
            best = max(best, spec["participant_points"])
            reasons.append(f"vc: {tier} participant ({', '.join(sorted(part_hits))}) -> {spec['participant_points']}")
        n = len(hits[tier])
        if n > 1 and spec["extra_points"]:
            add = min(spec["extra_cap"], spec["extra_points"] * (n - 1))
            extra += add
            reasons.append(f"vc: {n - 1} additional {tier} investor(s) -> +{add}")
    if best == 0 and (leads or others):
        best = VC_OTHER_NAMED_POINTS
        reasons.append(f"vc: named investors but none tiered -> {VC_OTHER_NAMED_POINTS}")
    amt = parse_usd(lr.get("amount_usd"))
    for threshold, pts in VC_AMOUNT_BONUS:
        if amt and amt >= threshold:
            extra += pts
            reasons.append(f"vc: latest round {lr.get('amount_usd')} >= ${threshold / 1e6:.0f}M -> +{pts}")
            break
    return int(min(100, round(best + extra))), reasons


def _val(v: Any) -> Any:
    """FindAll candidate.output values may be {value,type} dicts, JSON strings or raw values."""
    if isinstance(v, dict) and "value" in v:
        v = v["value"]
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in "[{":
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return v
    return v


def score_talent(leaders: list[dict]) -> tuple[int, list[str]]:
    reasons: list[str] = []
    totals = {k: 0.0 for k in TALENT_RUBRIC}
    for ld in leaders:
        conf = ld.get("_confidence", {})
        name = ld["name"]
        schools = " | ".join(ld.get("schools") or [])
        sh = _match_any(schools, TALENT_RUBRIC["top_school"]["names"])
        if sh:
            w = CONFIDENCE_WEIGHT.get(conf.get("education"), 0.8)
            totals["top_school"] += TALENT_RUBRIC["top_school"]["points"] * w
            reasons.append(f"talent: {name} top school ({', '.join(sh)}) x{w}")
        emps = " | ".join(ld.get("prior_companies") or [])
        eh = _match_any(emps, TALENT_RUBRIC["top_employer"]["names"])
        if eh:
            w = CONFIDENCE_WEIGHT.get(conf.get("prior_roles"), 0.8)
            totals["top_employer"] += TALENT_RUBRIC["top_employer"]["points"] * w
            reasons.append(f"talent: {name} top-tier employer ({', '.join(sorted(set(eh)))}) x{w}")
        # Founding a company scores nothing on its own; only an exit (acquired or IPO) counts.
        exits = [f for f in ld.get("_founded_raw") or [] if f.get("outcome") in ("acquired", "ipo")]
        if exits:
            w = CONFIDENCE_WEIGHT.get(conf.get("founded_before"), 0.8)
            totals["prior_exit"] += TALENT_RUBRIC["prior_exit"]["points"] * w
            reasons.append(
                f"talent: {name} prior exit ("
                + ", ".join(f"{f.get('company')} {f.get('outcome')}"
                            + (f" by {f['acquirer']}" if f.get("acquirer") else "") for f in exits)
                + f") x{w}")
        yrs = ld.get("years_experience")
        try:
            yrs_n = int(re.search(r"\d+", str(yrs)).group(0)) if yrs else None  # type: ignore[union-attr]
        except AttributeError:
            yrs_n = None
        if yrs_n and yrs_n >= TALENT_RUBRIC["senior_experience"]["min_years"]:
            w = CONFIDENCE_WEIGHT.get(conf.get("years_experience"), 0.8)
            totals["senior_experience"] += TALENT_RUBRIC["senior_experience"]["points"] * w
            reasons.append(f"talent: {name} {yrs_n}+ years experience x{w}")
    total = 0.0
    for k, v in totals.items():
        capped = min(v, TALENT_RUBRIC[k]["cap"])
        total += capped
        if v > capped:
            reasons.append(f"talent: {k} capped at {TALENT_RUBRIC[k]['cap']}")
    return int(min(100, round(total))), reasons


# ---- ATS check (free public APIs) ------------------------------------------
ATS_URL_PATTERNS = {
    "greenhouse": r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)",
    "ashby": r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)",
    "lever": r"jobs\.lever\.co/([A-Za-z0-9_-]+)",
}


def ats_check(provider: str | None, token: str | None, careers_url: str | None, out_dir: Path) -> dict:
    tried = []
    candidates: list[tuple[str, str]] = []
    if provider in ATS_URL_PATTERNS and token:
        candidates.append((provider, token))
    for prov, pat in ATS_URL_PATTERNS.items():
        m = re.search(pat, careers_url or "")
        if m and (prov, m.group(1)) not in candidates:
            candidates.append((prov, m.group(1)))
    result = {"provider": provider, "board_token": token, "verified": False, "job_count": None,
              "checked_url": None, "tried": tried}
    with httpx.Client(timeout=20, follow_redirects=True) as h:
        for prov, tok in candidates:
            url = {
                "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs",
                "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{tok}",
                "lever": f"https://api.lever.co/v0/postings/{tok}?mode=json",
            }[prov]
            try:
                r = h.get(url)
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
            except (httpx.HTTPError, json.JSONDecodeError) as e:
                tried.append({"provider": prov, "token": tok, "url": url, "error": str(e)})
                continue
            jobs = (data.get("jobs") if isinstance(data, dict) else data) if data is not None else None
            n = len(jobs) if isinstance(jobs, list) else None
            tried.append({"provider": prov, "token": tok, "url": url, "status": r.status_code, "job_count": n})
            write_json(out_dir / f"04-ats-{prov}.response.json",
                       {"url": url, "status": r.status_code, "job_count": n,
                        "sample_titles": [j.get("title") or j.get("text") for j in (jobs or [])[:10]
                                          if isinstance(j, dict)]})
            if r.status_code == 200 and n:
                result.update({"provider": prov, "board_token": tok, "verified": True, "job_count": n,
                               "checked_url": url})
                break
    return result


# ---- pipeline helpers --------------------------------------------------------
def _poll_findall(c, fid: str, max_wait: int, label: str) -> Any:
    t0 = time.time()
    while True:
        r = c.beta.findall.retrieve(fid)
        st = r.status
        m = st.metrics
        print(f"[{label} {int(time.time() - t0)}s] status={st.status} active={st.is_active} "
              f"generated={(m.generated_candidates_count if m else None) or 0} "
              f"matched={(m.matched_candidates_count if m else None) or 0} term={st.termination_reason}")
        if not st.is_active or time.time() - t0 > max_wait:
            return r
        time.sleep(10)


def _wait_task(c, run_id: str, max_wait: int) -> Any:
    import parallel

    t0 = time.time()
    while True:
        try:
            return c.task_run.result(run_id, api_timeout=min(300, max(30, max_wait)), timeout=400)
        except parallel.APIStatusError as e:
            if e.status_code == 408:
                print(f"[brief {int(time.time() - t0)}s] still running")
                if time.time() - t0 > max_wait:
                    raise TimeoutError(f"task {run_id} still running after {max_wait}s") from e
                continue
            raise


def _matched(result: Any) -> list[Any]:
    return [cd for cd in result.candidates if cd.match_status == "matched"]


def _citations(basis: Any, fields: set[str] | None = None) -> list[dict]:
    out = []
    for b in basis or []:
        fld = getattr(b, "field", None) if not isinstance(b, dict) else b.get("field")
        if fields and fld and fld.split(".")[0] not in fields:
            continue
        cits = (b.get("citations") if isinstance(b, dict) else getattr(b, "citations", None)) or []
        for ct in cits:
            url = ct.get("url") if isinstance(ct, dict) else getattr(ct, "url", None)
            title = ct.get("title") if isinstance(ct, dict) else getattr(ct, "title", None)
            if url:
                out.append({"url": url, "title": title, "field": fld})
    return out


def cmd_run_company(args: argparse.Namespace) -> None:
    import parallel

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(out, args.budget)
    state = read_json(out / "state.json", {})
    c = client()
    name, domain = args.name, normalize_domain(args.domain)
    issues: list[str] = []
    timings: dict[str, float] = {}

    def save_state() -> None:
        write_json(out / "state.json", state)

    # ---- 1. leadership via FindAll (create) --------------------------------
    gen = args.leadership_generator
    fixed, per = FINDALL_PRICE[gen]
    findall_req = {
        "objective": (f"Find the founders and current senior leadership team (CEO, CTO, other C-level "
                      f"executives, VPs and Heads of functions) of {name}, the company whose website is {domain}."),
        "entity_type": "people",
        "match_conditions": [{
            "name": "current_leader_at_company",
            "description": (
                f"The person is a founder/co-founder of {name} ({domain}) or currently holds a C-level "
                f"(CEO, CTO, COO, CPO, CFO, etc.), VP-level or Head-of role at {name} ({domain}). It must be "
                f"this exact company (the one at {domain}), not a different company with a similar name. "
                f"Evidence: the company's own website/team page, LinkedIn, press releases or news. Former "
                f"employees, investors, board-only members and advisors do NOT match. If there is no "
                f"evidence, the condition is not satisfied."),
        }],
        "generator": gen,
        "match_limit": args.match_limit,
        "metadata": {"poc": "launch-radar", "company": domain or name},
    }
    fa_id = state.get("findall_id")
    if not fa_id:
        est = ledger.reserve("findall.create", fixed + (0 if gen == "preview" else per * args.match_limit))
        f_req = write_json(out / "01-findall.request.json", findall_req)
        t0 = time.time()
        run = c.beta.findall.create(**findall_req)
        fa_id = run.findall_id
        state.update({"findall_id": fa_id, "findall_generator": gen, "findall_t0": t0, "findall_est": est})
        save_state()
        write_json(out / "01-findall.response.json", run)
        print(f"findall_id={fa_id}")
    else:
        print(f"[resume] findall_id={fa_id}")

    # ---- 3 (early). brief Task run (create now so it runs in parallel) ---------
    brief_proc = args.brief_processor
    brief_req = {
        "input": {
            "company_name": name,
            "company_domain": domain,
            "context": args.context or "Startup; may have recently announced a funding round or product launch.",
        },
        "processor": brief_proc,
        "task_spec": {"output_schema": {"type": "json", "json_schema": BRIEF_SCHEMA}},
        "metadata": {"poc": "launch-radar", "company": domain or name},
    }
    brief_id = state.get("brief_run_id")
    if not brief_id:
        est = ledger.reserve("task_run.create(brief)", TASK_PRICE[brief_proc])
        write_json(out / "03-brief.request.json", brief_req)
        state["brief_t0"] = time.time()
        tr = c.task_run.create(**brief_req)
        brief_id = tr.run_id
        state.update({"brief_run_id": brief_id, "brief_est": est})
        save_state()
        write_json(out / "03-brief.response.json", tr)
        print(f"brief run_id={brief_id}")

    # ---- 1b. wait for leadership ----------------------------------------------
    fa_run = _poll_findall(c, fa_id, args.max_wait, "findall")
    fa_res = c.beta.findall.result(fa_id)
    write_json(out / "01-findall.result.json", fa_res)
    matched = _matched(fa_res)
    timings["findall_s"] = round(time.time() - state["findall_t0"], 1)
    actual = fixed + per * len(matched)
    if "findall_logged" not in state:
        ledger.release(max(0.0, state["findall_est"] - ceil_cost(actual)))
        ledger.log(step="1-leadership", api="FindAll create+poll+result",
                   sdk_method="client.beta.findall.create / retrieve / result", processor=f"generator={gen}",
                   run_id=fa_id, latency_s=timings["findall_s"], est_cost_usd=state["findall_est"],
                   actual_cost_usd=round(actual, 4), matched=len(matched),
                   candidates=len(fa_res.candidates), termination=fa_run.status.termination_reason,
                   fixtures=[str(out / "01-findall.request.json"), str(out / "01-findall.response.json"),
                             str(out / "01-findall.result.json")])
        state["findall_logged"] = True
        save_state()
    print(f"leadership: {len(matched)} matched of {len(fa_res.candidates)} candidates")

    # optional fallback: preview found too few -> one base run
    if len(matched) < args.min_leaders and gen == "preview" and not state.get("findall_fallback_id"):
        b_fixed, b_per = FINDALL_PRICE["base"]
        try:
            est = ledger.reserve("findall.create(base fallback)", b_fixed + b_per * args.match_limit)
            req2 = dict(findall_req, generator="base")
            write_json(out / "01b-findall-base.request.json", req2)
            t0 = time.time()
            run2 = c.beta.findall.create(**req2)
            state.update({"findall_fallback_id": run2.findall_id})
            save_state()
            write_json(out / "01b-findall-base.response.json", run2)
            fa_run = _poll_findall(c, run2.findall_id, args.max_wait, "findall-base")
            fa_res = c.beta.findall.result(run2.findall_id)
            write_json(out / "01b-findall-base.result.json", fa_res)
            matched = _matched(fa_res)
            fa_id = run2.findall_id
            lat = round(time.time() - t0, 1)
            actual2 = b_fixed + b_per * len(matched)
            ledger.release(max(0.0, est - ceil_cost(actual2)))
            ledger.log(step="1b-leadership-fallback", api="FindAll create+poll+result",
                       sdk_method="client.beta.findall.create / retrieve / result", processor="generator=base",
                       run_id=fa_id, latency_s=lat, est_cost_usd=est, actual_cost_usd=round(actual2, 4),
                       matched=len(matched), fixtures=[str(out / "01b-findall-base.result.json")])
        except BudgetExceeded as e:
            issues.append(str(e))

    # ---- 2. pedigree via FindAll enrich --------------------------------------
    ped_proc = args.pedigree_processor
    enrich_keys = list(PEDIGREE_SCHEMA["properties"].keys())
    if matched and not state.get("enrich_requested_for") == fa_id:
        try:
            est = ledger.reserve("findall.enrich", TASK_PRICE[ped_proc] * len(matched))
            enrich_req = {"processor": ped_proc, "output_schema": {"type": "json", "json_schema": PEDIGREE_SCHEMA}}
            write_json(out / "02-enrich.request.json", {"findall_id": fa_id, **enrich_req})
            state["enrich_t0"] = time.time()
            er = c.beta.findall.enrich(fa_id, **enrich_req)
            write_json(out / "02-enrich.response.json", er)
            state.update({"enrich_requested_for": fa_id, "enrich_est": est, "enrich_n": len(matched)})
            save_state()
        except BudgetExceeded as e:
            issues.append(str(e))
        except parallel.APIStatusError as e:
            issues.append(f"enrich failed: {e.status_code} {e.message}")
            write_json(out / "02-enrich.error.json", {"status": e.status_code, "body": str(e.body)})
    if state.get("enrich_requested_for") == fa_id:
        t0 = time.time()
        while True:
            r = c.beta.findall.retrieve(fa_id)
            res = c.beta.findall.result(fa_id)
            m_now = _matched(res)
            done = [cd for cd in m_now if all(k in (cd.output or {}) for k in enrich_keys)]
            print(f"[enrich {int(time.time() - t0)}s] active={r.status.is_active} enriched={len(done)}/{len(m_now)}")
            if (not r.status.is_active and len(done) == len(m_now)) or time.time() - t0 > args.max_wait:
                break
            if not r.status.is_active and time.time() - t0 > 120:
                break  # inactive but some missing after a grace period: report, don't invent
            time.sleep(15)
        fa_res = res
        matched = m_now
        write_json(out / "02-enrich.result.json", res)
        timings["enrich_s"] = round(time.time() - state["enrich_t0"], 1)
        if len(done) < len(m_now):
            issues.append(f"enrichment missing for {len(m_now) - len(done)} of {len(m_now)} leaders")
        if "enrich_logged" not in state:
            n_enriched = len(done)
            actual = TASK_PRICE[ped_proc] * n_enriched
            ledger.release(max(0.0, state["enrich_est"] - ceil_cost(actual)))
            ledger.log(step="2-pedigree", api="FindAll enrich (Task processor per matched leader)",
                       sdk_method="client.beta.findall.enrich + result", processor=ped_proc, run_id=fa_id,
                       latency_s=timings["enrich_s"], est_cost_usd=state["enrich_est"],
                       actual_cost_usd=round(actual, 4), enriched=n_enriched,
                       fixtures=[str(out / "02-enrich.request.json"), str(out / "02-enrich.response.json"),
                                 str(out / "02-enrich.result.json")])
            state["enrich_logged"] = True
            save_state()

    # ---- 3b. wait for brief ------------------------------------------------------
    brief: dict = {}
    brief_basis: list = []
    try:
        br = _wait_task(c, brief_id, args.max_wait)
        write_json(out / "03-brief.result.json", br)
        timings["brief_s"] = round(time.time() - state["brief_t0"], 1)
        brief = br.output.content if br.output.type == "json" else {}
        brief = _parse_content(brief)
        brief_basis = br.output.basis or []
        if "brief_logged" not in state:
            ledger.log(step="3-brief", api="Task run create+result", sdk_method="client.task_run.create / result",
                       processor=brief_proc, run_id=brief_id, latency_s=timings["brief_s"],
                       est_cost_usd=state["brief_est"], actual_cost_usd=TASK_PRICE[brief_proc],
                       fixtures=[str(out / "03-brief.request.json"), str(out / "03-brief.response.json"),
                                 str(out / "03-brief.result.json")])
            state["brief_logged"] = True
            save_state()
    except (parallel.APIStatusError, TimeoutError) as e:
        issues.append(f"brief failed: {e}")
        try:
            write_json(out / "03-brief.retrieve.json", c.task_run.retrieve(brief_id))
        except parallel.APIError:
            pass

    # ---- 4. ATS check -----------------------------------------------------------
    ats_in = brief.get("ats") or {}
    ats = ats_check(ats_in.get("provider"), ats_in.get("board_token"), brief.get("careers_url"), out)
    ats["model_provider"] = ats_in.get("provider")
    ats["model_board_token"] = ats_in.get("board_token")
    ledger.log(step="4-ats-check", api="public ATS job-board API (not Parallel)", sdk_method="httpx.get",
               processor=None, run_id=None, latency_s=None, est_cost_usd=0.0, result=ats,
               fixtures=[t.get("url") for t in ats["tried"]])
    pr_ready = bool(ats["verified"] and ats["provider"] in ("greenhouse", "ashby", "lever"))

    # ---- 5. leaders + scoring -----------------------------------------------------
    leaders = []
    for cd in matched:
        o = cd.output or {}
        conf = {}
        for b in cd.basis or []:
            conf[b.field.split(".")[0]] = b.confidence
        edu = _val(o.get("education")) or []
        roles = _val(o.get("prior_roles")) or []
        fb = _val(o.get("founded_before")) or []
        edu = edu if isinstance(edu, list) else []
        roles = roles if isinstance(roles, list) else []
        fb = fb if isinstance(fb, list) else []
        cond = o.get("current_leader_at_company")
        ld = {
            "name": cd.name,
            "title": _val(o.get("current_title")) or (_val(cond) if isinstance(_val(cond), str) else None),
            "linkedin_url": _val(o.get("linkedin_url")) or (cd.url if "linkedin.com" in (cd.url or "") else None),
            "schools": [" ".join(x for x in [e.get("school"), e.get("degree"), e.get("field")] if x)
                        for e in edu if isinstance(e, dict)],
            "prior_companies": [f"{r.get('company')}" + (f" ({r['title']})" if r.get("title") else "")
                                for r in roles if isinstance(r, dict)],
            "founded_before": [f"{f.get('company')} ({f.get('outcome')}"
                               + (f", acq. by {f['acquirer']}" if f.get("acquirer") else "")
                               + (f", {f['exit_year']}" if f.get("exit_year") else "") + ")"
                               for f in fb if isinstance(f, dict)],
            "years_experience": _val(o.get("years_experience")),
            "industry_experience": _val(o.get("industry_experience_summary")),
            "signals": [],
            "_founded_raw": [f for f in fb if isinstance(f, dict)],
            "_confidence": conf,
            "profile_url": cd.url,
        }
        notable = _val(o.get("notable_signals")) or []
        ld["notable"] = notable if isinstance(notable, list) else [str(notable)]
        leaders.append(ld)

    talent, t_reasons = score_talent(leaders)
    vc, v_reasons = score_vc(brief)
    for ld in leaders:  # per-leader signal tags for the card
        ld["signals"] = [r.split(f"{ld['name']} ", 1)[1] for r in t_reasons if f" {ld['name']} " in r]
        ld["signals"] += [s for s in ld.pop("notable")[:4]]
        ld.pop("_founded_raw")
        ld["confidence"] = ld.pop("_confidence")

    # ---- 6. card.json --------------------------------------------------------------
    event = None
    if args.event:
        p = Path(args.event)
        event = json.loads(p.read_text()) if p.exists() else json.loads(args.event)
        event = {"type": event.get("event_type") or event.get("type"), "headline": event.get("headline"),
                 "source_url": event.get("source_url"), "announced_at": event.get("announced_at"),
                 "origin": "monitor"}
    elif brief.get("latest_announcement"):
        la = brief["latest_announcement"]
        event = {"type": la.get("kind"), "headline": la.get("headline"), "source_url": la.get("url"),
                 "announced_at": la.get("announced_at"), "origin": "task brief"}

    sources: list[dict] = []
    seen_urls: set[str] = set()
    for s in _citations(brief_basis) + [x for cd in matched for x in _citations(cd.basis)]:
        if s["url"] not in seen_urls:
            seen_urls.add(s["url"])
            sources.append(s)
    lr = brief.get("latest_round") or {}
    spend = read_json(out / "spend.json", {})
    card = {
        "company": name,
        "domain": domain,
        "website": brief.get("website_url") or f"https://{domain}",
        "one_liner": brief.get("one_liner"),
        "event": event,
        "scores": {"talent": talent, "vc": vc, "reasons": v_reasons + t_reasons},
        "blurb": brief.get("blurb"),
        "what_they_do": brief.get("what_they_do"),
        "notable_facts": brief.get("notable_facts") or [],
        "leaders": leaders,
        "funding": {
            "latest_round": lr,
            "prior_rounds": brief.get("prior_rounds") or [],
            "total_raised_usd": brief.get("total_raised_usd"),
        },
        "careers_url": brief.get("careers_url"),
        "ats": {k: ats[k] for k in ("provider", "board_token", "verified", "job_count", "checked_url",
                                    "model_provider", "model_board_token")},
        "pr_ready": pr_ready,
        "sources": sources[:40],
        "parallel_run_ids": {
            "findall_id": state.get("findall_id"),
            "findall_fallback_id": state.get("findall_fallback_id"),
            "enrich_on_findall_id": state.get("enrich_requested_for"),
            "brief_task_run_id": brief_id,
        },
        "cost_usd": spend.get("actual_estimate_usd"),
        "timings_s": timings,
        "issues": issues,
        "generated_at": now_iso(),
    }
    f_card = write_json(out / "card.json", card)
    print(json.dumps({"card": f_card, "talent": talent, "vc": vc, "leaders": [l["name"] for l in leaders],
                      "pr_ready": pr_ready, "ats": card["ats"], "spend": read_json(out / "spend.json", {}),
                      "issues": issues}, indent=2))


# ---------------------------------------------------------------------------
# dedupe
# ---------------------------------------------------------------------------
def cmd_dedupe(args: argparse.Namespace) -> None:
    data = json.loads(Path(args.candidates).read_text())
    if isinstance(data, dict):
        data = data.get("kept") or data.get("candidates") or [data]
    seen: dict = read_json(SEEN_FILE, {})
    accepted, rejected = [], []
    for item in data:
        raw = item.get("domain") or item.get("company_domain")
        dom = normalize_domain(raw)
        if not dom:
            rejected.append({"name": item.get("name"), "raw_domain": raw, "reason": "no valid domain"})
        elif dom in seen:
            rejected.append({"name": item.get("name"), "raw_domain": raw, "domain": dom,
                             "reason": f"already posted at {seen[dom]['posted_at']}"})
        else:
            seen[dom] = {"name": item.get("name"), "posted_at": now_iso()}
            accepted.append({"name": item.get("name"), "raw_domain": raw, "domain": dom})
    if not args.dry_run:
        write_json(SEEN_FILE, seen)
    print(json.dumps({"accepted": accepted, "rejected": rejected, "seen_size": len(seen),
                      "seen_file": str(SEEN_FILE), "dry_run": args.dry_run}, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("monitor-create")
    s.add_argument("--processor", default="lite", choices=["lite", "base"])
    s.add_argument("--frequency", default="1d")
    s.add_argument("--budget", type=float, default=0.05)
    s.add_argument("--force-new", action="store_true")
    s.set_defaults(fn=cmd_monitor_create)

    s = sub.add_parser("monitor-events")
    s.add_argument("--monitor-id")
    s.add_argument("--max-wait", type=int, default=480)
    s.add_argument("--interval", type=int, default=30)
    s.add_argument("--settle", type=int, default=30)
    s.add_argument("--budget", type=float, default=0.05)
    s.set_defaults(fn=cmd_monitor_events)

    s = sub.add_parser("monitor-cancel")
    s.add_argument("--monitor-id")
    s.add_argument("--budget", type=float, default=0.05)
    s.set_defaults(fn=cmd_monitor_cancel)

    s = sub.add_parser("run-company")
    s.add_argument("--name", required=True)
    s.add_argument("--domain", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--budget", type=float, required=True)
    s.add_argument("--context")
    s.add_argument("--event", help="monitor candidate JSON (string or file) to use as the card event")
    s.add_argument("--leadership-generator", default="preview", choices=["preview", "base"])
    s.add_argument("--match-limit", type=int, default=8)
    s.add_argument("--min-leaders", type=int, default=2, help="below this, preview falls back to one base run")
    s.add_argument("--pedigree-processor", default="core", choices=["lite", "base", "core"])
    s.add_argument("--brief-processor", default="core", choices=["lite", "base", "core", "pro"])
    s.add_argument("--max-wait", type=int, default=900)
    s.set_defaults(fn=cmd_run_company)

    s = sub.add_parser("dedupe")
    s.add_argument("--candidates", required=True)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_dedupe)

    args = p.parse_args()
    try:
        args.fn(args)
    except BudgetExceeded as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
