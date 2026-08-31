# Browserbase Agent — recipe authoring experiment

An experiment, not a shipped path. The question it answers: **can an agent with a live
browser produce a recipe our replay tier can run, on boards our one-shot Haiku synthesis
gets wrong?**

Paste `SYSTEM-PROMPT.md` into the Agent's **System prompt** field and
`result-schema.json` into its **Result schema** field, then run one board per task.

## The task prompt

Per-run input only. Keep it copyable so runs stay comparable.

```
Build a recipe for the job board at %board_url%.
Return schema-valid JSON at the top level.
```

Supply `%board_url%` as a variable. Boards worth running, hardest last:

| Board | URL | Why it is in the list |
|---|---|---|
| Atlassian | `https://www.atlassian.com/company/careers/all-jobs` | our synthesis mapped `location` to a path that is null on every record, and `description` to identical boilerplate |
| Jane Street | `https://www.janestreet.com/join-jane-street/open-roles/` | the real per-job URL is only in the page's anchors, never in a network request — every job link 404s |
| Goldman Sachs | `https://higher.gs.com/roles` | publishes two ids per role and only one of them routes; the SPA answers 200 for any path |
| Walmart | `https://careers.walmart.com/` | 48,800 jobs behind a page parameter nested four levels into a POST body. The real test. |

## Why the previous agent burned its whole budget

The earlier prompt (`~/Downloads/job-board-scraper-agent.yaml`) asked for **a scraper plus
proof it read the whole board**. On Walmart that instruction is only satisfiable by
enumeration: the agent ran two complete crawls of ~48,850 jobs across ~6,200 requests
each, then launched a third, and polled them with `nohup` + `sleep 240..295` in a loop.
It logged 4,466 active seconds against a 99-minute wall clock — **most of the spend was
waiting, not working** — and hit the $5 cap without producing a usable artifact.

The fix is not a `--max-jobs` flag. It is that **the deliverable changed**: a recipe is a
mechanism, and a mechanism is provable on two pages.

| Old contract | This one |
|---|---|
| Write a scraper | Describe the request |
| Prove you read the whole board | Record *how a replay could know* it did — the oracle — in one request |
| Run it twice and diff the ids | Re-issue page 1 twice and diff |
| (unbounded) | ≤ 40 requests, ≤ 3 pages, ≤ 150 records, ≤ 8 detail fetches |
| (unbounded) | no background processes, no `sleep` > 5s, no polling |

Set the run budget to **$2**, not $5. At $5 there is room to attempt a full crawl before
the cap bites; at $2 a bounded proof strategy is the only one that finishes.

## What a good result looks like

`status: "recipe_ready"` with all four `evidence` blocks populated with real numbers, and
`budget.exceeded_a_ceiling: false`.

`status: "recipe_partial"` with a specific `blockers` entry is also a good outcome — it
tells us which half of the problem the agent approach actually solves.

The result maps onto `company_scripts.script` (see `recipe_schema.py`), so a `recipe_ready`
result is directly comparable against what discovery synthesized for the same board.

## What this is being weighed against

Discovery-time acceptance probes: deterministic checks that run after our own synthesis
and before the recipe is stored. Those **raise the floor** — they stop wrong recipes from
shipping silently. An agent **raises the ceiling** — it can manipulate the page and correct
itself, so it can be right where a one-shot model is wrong.

They are complementary, not alternatives. The probes stay worth having regardless, because
an agent's answer still needs checking. What this experiment decides is how much further
the floor is worth lifting before paying for the ceiling.
