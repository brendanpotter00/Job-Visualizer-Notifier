# Custom Dashboards — Feature Spec

> **Status:** Proposed (candidate feature, `custom-dashboards` in the voting page).
> **One-line summary (as shown on the voting page):** _Describe a dashboard in plain
> language and AI lays out live charts, ranked lists, and graphs from your job data —
> placing each component where you ask._
>
> This doc is the long-form brief so any agent/contributor can pick the feature up
> without a re-explanation. It captures product intent and the intended architecture;
> it is **not** a committed implementation plan (no schema/endpoints are frozen yet).

## Context

Today the app shows a fixed set of views: per-company hiring trends, a recent-jobs feed,
and (soon) resume-match notifications. Every user sees the same layout. Power users want
to answer their *own* questions — "how are my matches at Google trending?", "which
companies posted the most roles I qualify for this week?" — without us shipping a bespoke
page for each one.

**Custom Dashboards** lets a signed-in user assemble a personal dashboard by *describing
it in natural language*. The user says what they want and where; an AI agent composes the
dashboard from a library of prebuilt, parameterized visual components, pulling the user's
own job/match data through structured tools. The result is a saved, reloadable layout of
live components — not a one-off screenshot.

The core bet: **the layout and the data binding are the hard part for a human, but easy to
express in words.** "Top-left: my top job matches, Google only. Top-middle: a vertical
list of all my matches. Below it: a line graph of my matches over time, by day." That
sentence should produce a working dashboard.

## What the user experiences

1. User opens **Custom Dashboards** and types (or speaks) what they want, e.g.:
   - "Put a component in the **top left** with my **top job matches from Google only**."
   - "**Top middle**, a tall vertical component listing **all my matches**."
   - "**Below that**, a **line graph of my matches over time, by day**."
2. The AI interprets each request into `(component type, grid position/size, data query)`
   tuples and renders them into a responsive grid.
3. The user can keep refining in natural language ("make the line graph weekly instead",
   "add a bar graph of matches by company to the right"), rearrange, or remove components.
4. The dashboard is **saved per user** and reloads with live data on each visit.

## Architecture — three pillars

### 1. A design system + a library of prebuilt, parameterized components

We do **not** let the AI emit arbitrary code into the page. Instead we give it a curated,
typed catalog of components, each with a strict props contract. The AI only chooses *which*
component, *where* it goes, and *what data query* feeds it. Candidate v1 components:

| Component        | Purpose                                   | Key params (sketch)                          |
| ---------------- | ----------------------------------------- | -------------------------------------------- |
| Line graph       | A metric over time                        | `metric`, `bucket` (day/week), `series`      |
| Bar graph        | A metric grouped by a dimension           | `metric`, `groupBy` (company/location/level) |
| Ranked list      | Top-N entities                            | `entity` (jobs/companies), `rankBy`, `limit` |
| Stat / count tile| A single headline number                  | `metric`, `window`                           |
| Job list         | A scrollable list of matching jobs        | `filter`, `sort`, `limit`                    |

Each component reuses the existing visual language (Material-UI + Recharts, the same theme
as the rest of the app — see `src/frontend/src/config/theme.ts`). The "design system" is the
shared set of tokens, chart styles, spacing, and the grid these components snap into, so a
generated dashboard looks native, not bolted-on.

The component contracts (names, props, allowed enums) become the **schema the AI plans
against** — analogous to how a tool schema constrains a tool call. A planning step that
emits an invalid component/param is rejected and retried, exactly like structured output
elsewhere in the codebase.

### 2. Parameterized data access via MCP tools

The AI must pull the *user's own* data in a structured shape — never freehand SQL, never
the raw DB. Expose a small set of **parameterized, read-only MCP tools** (or an equivalent
internal tool layer) that return job/match data scoped to the authenticated user:

- `get_matches(company?, dateRange?, level?, location?, limit?, sort?)` → ranked job matches
- `get_match_timeseries(bucket=day|week, company?, dateRange?)` → counts over time
- `get_match_breakdown(groupBy=company|location|level, dateRange?)` → grouped counts

Properties these tools must have:

- **Scoped to the caller.** Every tool is bound to the signed-in user; it can only read
  that user's matches/jobs. No cross-user access.
- **Structured + typed output.** Returns JSON shaped for direct binding to a component's
  data prop, so the AI maps a request → tool call → component without transformation glue.
- **Parameterized, not generative.** The AI fills declared parameters; it cannot inject
  arbitrary query logic. This is the safety boundary.

This dovetails with the **Hosted MCP server** candidate feature (`mcp-server`): the same
parameterized data surface that lets external agents query job data can back the dashboard
composer. Build the data tools once; reuse them here and there. Note the existing SSRF/data
boundaries already enforced server-side (e.g. allowlists in
`src/backend/api/services/eightfold_client.py`) as the precedent for "tools have hard limits."

### 3. Natural-language → layout composition

The composition step turns a user utterance into a dashboard mutation. Conceptually:

```
user text ──▶ planner (LLM) ──▶ [ { component, gridPos:{x,y,w,h}, dataQuery } ... ]
                                   │
                                   ├─ validate against component schema (retry on miss)
                                   ├─ resolve each dataQuery to an MCP tool call
                                   └─ render into the responsive grid + persist layout
```

- **Positioning vocabulary.** Map natural phrases ("top left", "top middle", "below it",
  "to the right of the line graph") to grid coordinates. Support both absolute ("top left")
  and relative ("below that") placement; relative placement needs the planner to know the
  current layout, so pass the existing dashboard as context.
- **Incremental edits.** Treat each utterance as a patch on the current layout (add/move/
  remove/retune a component), not a full regeneration, so refinements are cheap and stable.
- **Persistence.** Save the resolved layout (component list + positions + bound queries)
  per user so it reloads with fresh data. Data is always re-fetched live via the tools;
  only the *layout + query bindings* are stored.

## Data model (sketch — not frozen)

A new per-user table, e.g. `user_dashboards` (FK to `users.id`), storing one or more named
dashboards as a validated JSON layout:

```jsonc
{
  "name": "My job hunt",
  "components": [
    { "id": "c1", "type": "rankedList", "grid": { "x": 0, "y": 0, "w": 4, "h": 4 },
      "query": { "tool": "get_matches", "params": { "company": "google", "limit": 10, "sort": "score" } } },
    { "id": "c2", "type": "jobList", "grid": { "x": 4, "y": 0, "w": 4, "h": 8 },
      "query": { "tool": "get_matches", "params": {} } },
    { "id": "c3", "type": "lineGraph", "grid": { "x": 4, "y": 8, "w": 4, "h": 4 },
      "query": { "tool": "get_match_timeseries", "params": { "bucket": "day" } } }
  ]
}
```

Follow the project's migration rules: add the model to `src/backend/api/db_models.py` and
`alembic revision --autogenerate` (never hand-write a revision; combined-ALTER convention).
The layout JSON should be **validated against the component schema on write** so a corrupt
or stale layout can't break the renderer.

## Dependencies & relationship to other features

- **Resume matching (`resume-match-ai`)** produces the "matches" this dashboard visualizes —
  it's the upstream data source. Custom Dashboards is most valuable once matches exist.
- **Hosted MCP server (`mcp-server`)** shares the parameterized data-tool layer. Designing
  the dashboard's data tools and the public MCP tools together avoids building the surface
  twice.
- **Location normalization (shipped)** makes `groupBy=location` and location filters
  coherent — without it, "matches by location" fragments across "SF / Bay Area / San
  Francisco, CA". This is part of why it shipped first.

## Open questions

- **Build vs. buy the grid** — adopt a library (e.g. a react-grid-layout style system) or a
  lighter CSS-grid composer? Drag-to-rearrange is a stretch goal; NL placement is v1.
- **Planner model + cost** — which model plans the layout, and do we cache plans? Editing
  should be incremental to keep token cost down.
- **Safety of data tools** — finalize the exact parameter allowlists and per-user scoping so
  the AI can never widen access beyond the caller's own data.
- **Component catalog scope for v1** — start with line graph, bar graph, ranked list, stat
  tile, job list; expand based on usage.

## Suggested build order (when greenlit)

1. Ship the parameterized, user-scoped data tools (line them up with the MCP-server work).
2. Build the prebuilt component library + a static grid that renders a hand-written layout
   JSON (no AI yet) — proves the rendering + data binding end to end.
3. Add the NL planner that emits/patches layout JSON validated against the component schema.
4. Add per-user persistence (`user_dashboards`) + the page UI and NL input.
5. Add incremental edits and (stretch) drag-to-rearrange.
