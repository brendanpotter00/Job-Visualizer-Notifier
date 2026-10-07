# /// script
# requires-python = ">=3.10"
# dependencies = ["parallel-web>=1.3.5", "httpx"]
# ///
"""Team pedigree stats (non-founders) for one company: two approaches, side by side.

Subcommands:
  task   Option A: one Task run that finds public team profiles and returns the tallies itself.
  group  Option B: Entity Search lists people, a Task Group checks each one (base),
         and this script does the counting.

Both write fixtures to --out (requests, responses, a summary.json, spend.json).
The API key comes from PARALLEL_API_KEY via the SDK; it is never printed or stored.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from poc import TALENT_RUBRIC, _match_any, _wait_task, client, write_json  # noqa: E402

PRICE = {"lite": 0.005, "base": 0.01, "core": 0.025, "pro": 0.10, "entity_search": 0.005}
MAX_PEOPLE = 30


def _founders(card_path: Path) -> list[str]:
    card = json.loads(card_path.read_text())
    return [ld["name"] for ld in card.get("leaders", [])]


def _top(counter: Counter, n: int = 8) -> list[dict]:
    return [{"name": k, "count": v} for k, v in counter.most_common(n)]


# ---- Option A: one Task run returns the tallies ---------------------------------
TALLY = {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["name", "count"], "additionalProperties": False}}

A_SCHEMA = {
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


def cmd_task(args: argparse.Namespace) -> None:
    out = Path(args.out)
    founders = _founders(Path(args.card))
    req = {
        "input": (f"Company: {args.name} ({args.domain}). Find current employees of this exact company "
                  f"who are NOT its founders ({', '.join(founders)}). Use public profiles (LinkedIn, team "
                  f"pages, personal sites). For the people you find, tally the universities they attended "
                  f"and their notable previous employers. Count each person once per school and per employer. "
                  f"Do not guess: only count facts you found."),
        "processor": args.processor,
        "task_spec": {"output_schema": {"type": "json", "json_schema": A_SCHEMA}},
        "metadata": {"poc": "launch-radar-team", "company": args.domain, "option": "A"},
    }
    write_json(out / "A-task.request.json", req)
    c = client()
    t0 = time.time()
    run = c.task_run.create(**req)
    write_json(out / "A-task.created.json", run)
    print(f"[A] run_id={run.run_id} processor={args.processor} est=${PRICE[args.processor]:.3f}")
    res = _wait_task(c, run.run_id, args.max_wait)
    secs = round(time.time() - t0, 1)
    write_json(out / "A-task.result.json", res)
    content = res.output.content
    write_json(out / "A-summary.json", {"option": "A", "latency_s": secs,
                                        "cost_usd": PRICE[args.processor], "result": content})
    write_json(out / "A-spend.json", {"task_run": PRICE[args.processor]})
    print(json.dumps({"latency_s": secs, **content}, indent=2)[:3000])


# ---- Option B: Entity Search -> Task Group (base) -> count locally ----------------
B_SCHEMA = {
    "type": "object",
    "properties": {
        "works_at_company_now": {"type": "boolean", "description":
                                 "True only if this person currently works at the named company."},
        "current_title": {"type": ["string", "null"]},
        "schools": {"type": "array", "items": {"type": "string"},
                    "description": "Universities attended (name only). Empty if unknown."},
        "prior_employers": {"type": "array", "items": {"type": "string"},
                            "description": "Previous employers (company name only), most recent first. Empty if unknown."},
        "founded_company_with_exit": {"type": "boolean", "description":
                                      "True only if they founded a company that was acquired or IPO'd."},
    },
    "required": ["works_at_company_now", "current_title", "schools", "prior_employers",
                 "founded_company_with_exit"],
    "additionalProperties": False,
}


def cmd_group(args: argparse.Namespace) -> None:
    from parallel.types import ErrorEvent

    out = Path(args.out)
    founders = {n.lower() for n in _founders(Path(args.card))}
    c = client()
    spend = {"entity_search": PRICE["entity_search"]}

    es_req = {"entity_type": "people", "match_limit": 100,
              "objective": f"People who currently work at {args.name} ({args.domain})"}
    write_json(out / "B-1-entity-search.request.json", es_req)
    t0 = time.time()
    es = c.beta.findall.entity_search(**es_req)
    write_json(out / "B-1-entity-search.response.json", es)
    people = [e for e in es.entities if (e.name or "").lower() not in founders][:MAX_PEOPLE]
    print(f"[B] entity search: {len(es.entities)} people in {time.time() - t0:.1f}s; "
          f"checking {len(people)} non-founders")

    spec = {"output_schema": {"type": "json", "json_schema": B_SCHEMA}}
    inputs = [{"input": {"person_name": e.name, "profile_url": e.url, "description": e.description,
                         "company_name": args.name, "company_domain": args.domain},
               "processor": args.processor, "metadata": {"i": str(i)}} for i, e in enumerate(people)]
    write_json(out / "B-2-task-group.request.json", {"default_task_spec": spec, "inputs": inputs})
    group_id = c.task_group.create(metadata={"poc": "launch-radar-team", "company": args.domain}).task_group_id
    c.task_group.add_runs(group_id, inputs=inputs, default_task_spec=spec)
    print(f"[B] task group {group_id}: {len(inputs)} runs on {args.processor} "
          f"est=${len(inputs) * PRICE[args.processor]:.3f}")
    while True:
        st = c.task_group.retrieve(group_id).status
        print(f"[B {int(time.time() - t0)}s] {st.task_run_status_counts}")
        if not st.is_active or time.time() - t0 > args.max_wait:
            break
        time.sleep(15)

    rows, completed = [], 0
    for ev in c.task_group.get_runs(group_id, include_input=True, include_output=True):
        if isinstance(ev, ErrorEvent):
            print("[B] stream error:", ev.error.message)
            continue
        if ev.run.status == "completed" and ev.output is not None:
            completed += 1
            i = int((ev.run.metadata or {}).get("i", -1))
            rows.append({"name": people[i].name if 0 <= i < len(people) else None, **ev.output.content})
    write_json(out / "B-2-task-group.results.json", rows)
    spend["task_group"] = round(completed * PRICE[args.processor], 4)  # failed runs are not billed

    staff = [r for r in rows if r.get("works_at_company_now")]
    schools, employers = Counter(), Counter()
    top_school = top_emp = exits = 0
    for r in staff:
        schools.update({s.strip() for s in r.get("schools") or [] if s and s.strip()})
        employers.update({e.strip() for e in r.get("prior_employers") or [] if e and e.strip()})
        top_school += bool(_match_any(" | ".join(r.get("schools") or []), TALENT_RUBRIC["top_school"]["names"]))
        top_emp += bool(_match_any(" | ".join(r.get("prior_employers") or []),
                                   TALENT_RUBRIC["top_employer"]["names"]))
        exits += bool(r.get("founded_company_with_exit"))
    summary = {
        "option": "B", "latency_s": round(time.time() - t0, 1), "cost_usd": round(sum(spend.values()), 4),
        "entity_search_results": len(es.entities), "checked": len(people), "completed": completed,
        "confirmed_current_staff": len(staff),
        "schools": _top(schools), "prior_employers": _top(employers),
        "with_top_school": top_school, "with_top_employer": top_emp, "ex_founders_with_exit": exits,
        "staff_names": [r["name"] for r in staff],
    }
    write_json(out / "B-summary.json", summary)
    write_json(out / "B-spend.json", spend)
    print(json.dumps(summary, indent=2)[:3000])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, proc in (("task", cmd_task, "pro"), ("group", cmd_group, "base")):
        s = sub.add_parser(name)
        s.add_argument("--name", required=True)
        s.add_argument("--domain", required=True)
        s.add_argument("--card", required=True, help="card.json from run-company (founders are excluded)")
        s.add_argument("--out", required=True)
        s.add_argument("--processor", default=proc, choices=["lite", "base", "core", "pro"])
        s.add_argument("--max-wait", type=int, default=900)
        s.set_defaults(fn=fn)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
