# /// script
# requires-python = ">=3.10"
# dependencies = ["parallel-web>=1.3.5", "httpx"]
# ///
"""Leader pedigree with a Task Group only (no FindAll enrich): one run per leader.

  uv run scripts/launch_radar_poc/pedigree_group.py --card out/raindrop-ai/card.json \
      --out out/raindrop-ai/pedigree-base --processor base

Reads the leaders FindAll matched (from card.json), runs PEDIGREE_SCHEMA once per leader,
and writes the request, the results, a summary and spend.json to --out.
The API key comes from PARALLEL_API_KEY via the SDK; it is never printed or stored.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from poc import PEDIGREE_SCHEMA, client, write_json  # noqa: E402

PRICE = {"lite": 0.005, "base": 0.01, "core": 0.025, "pro": 0.10}
MAX_LEADERS = 10


def main() -> None:
    from parallel.types import ErrorEvent

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--card", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--processor", default="base", choices=list(PRICE))
    ap.add_argument("--max-wait", type=int, default=600)
    args = ap.parse_args()

    card = json.loads(Path(args.card).read_text())
    out = Path(args.out)
    leaders = card["leaders"][:MAX_LEADERS]
    spec = {"output_schema": {"type": "json", "json_schema": PEDIGREE_SCHEMA}}
    inputs = [{"input": {"person_name": ld["name"], "current_title": ld.get("title"),
                         "linkedin_url": ld.get("linkedin_url"),
                         "company_name": card["company"], "company_domain": card["domain"]},
               "processor": args.processor, "metadata": {"i": str(i)}} for i, ld in enumerate(leaders)]
    write_json(out / "pedigree-group.request.json", {"default_task_spec": spec, "inputs": inputs})

    c = client()
    t0 = time.time()
    group_id = c.task_group.create(metadata={"poc": "launch-radar-pedigree", "company": card["domain"]}).task_group_id
    c.task_group.add_runs(group_id, inputs=inputs, default_task_spec=spec)
    print(f"task group {group_id}: {len(inputs)} runs on {args.processor} "
          f"est=${len(inputs) * PRICE[args.processor]:.3f}", flush=True)
    while True:
        st = c.task_group.retrieve(group_id).status
        print(f"[{int(time.time() - t0)}s] {st.task_run_status_counts}", flush=True)
        if not st.is_active or time.time() - t0 > args.max_wait:
            break
        time.sleep(10)

    rows = []
    for ev in c.task_group.get_runs(group_id, include_input=True, include_output=True):
        if isinstance(ev, ErrorEvent):
            print("stream error:", ev.error.message)
            continue
        if ev.run.status == "completed" and ev.output is not None:
            i = int((ev.run.metadata or {}).get("i", -1))
            basis = [{"field": b.field, "confidence": b.confidence, "citations": len(b.citations or [])}
                     for b in (ev.output.basis or [])]
            rows.append({"name": leaders[i]["name"], "run_id": ev.run.run_id,
                         "output": ev.output.content, "basis": basis})
    write_json(out / "pedigree-group.results.json", rows)
    spend = {"task_group": round(len(rows) * PRICE[args.processor], 4)}  # failed runs are not billed
    write_json(out / "spend.json", spend)
    summary = {"group_id": group_id, "processor": args.processor, "leaders": len(inputs), "completed": len(rows),
               "wall_s": round(time.time() - t0, 1), "cost_usd": spend["task_group"]}
    write_json(out / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
