# tiktok (lifeattiktok.com) — discovery findings

Date: 2026-08-05. Entry URL `https://lifeattiktok.com/search` loaded fine (no 404, no bot wall).

## Technique that worked

**Plain HTTP JSON POST — no browser needed.**

- Endpoint: `POST https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts`
- Body (JSON):
  ```json
  {"recruitment_id_list": [], "job_category_id_list": [], "subject_id_list": [],
   "location_code_list": [], "keyword": "", "limit": 1000, "offset": 0}
  ```
- Response envelope: `{code: 0, message: "ok", data: {job_post_list: [...], count: 3799}}`.
  `data.count` is the site's own total-jobs oracle.

### Load-bearing headers (ablation-tested one at a time, `_probe_httpx.py`)

| Header removed | Result |
|---|---|
| `website-path: tiktok` | **HTTP 400 `invalid request`** |
| Origin / Referer / User-Agent / Accept / Accept-Language | 200, identical payload |
| only `website-path: tiktok`, nothing else | 200, identical payload |
| no headers at all | HTTP 400 `invalid request` |

`website-path: tiktok` is the single mandatory header. That is the valuable finding: a naive
copy of "browser-looking" headers would work but hide which one matters; a naive curl with
none would 400 and mislead you into thinking a browser is required.

### Pagination (`_probe_pagination.py`, `_probe_limit2000.py`)

- Scheme: `offset` + `limit` inside the POST body (replay.py merges the pagination param
  into the JSON body for POST entrypoints — exactly what this needs).
- `limit` honored at least up to **2000** (12/100/500/1000/2000 all returned exactly that many).
  Recipe uses 1000: ~4.6 MB/response, 4 requests per replay.
- Ordering is stable across page sizes (first 100 of a limit=500 call == the limit=100 page).
- Adjacent pages have zero id overlap.
- Past-the-end offset (3750 of 3799) returns a short page (49 rows) — the replay's
  `len(page) < page_size` end condition terminates correctly. No hard offset cap observed
  within the current dataset size.

## Gotchas that would break a naive implementation

1. **Playwright cannot see the POST body.** `request.post_data` is `null` (the site sends the
   body as a stream). Only `content-length: 132` was visible. The body was reconstructed from
   ByteDance careers API conventions and verified byte-exact (132 bytes, identical response).
   A discovery flow that trusts `post_data` alone would dead-end here.
2. **No URL field in the records.** Detail pages are `https://lifeattiktok.com/search/<id>`
   (confirmed via the site's own RSC prefetch requests, e.g. `/search/7668827379083823413?_rsc=…`).
   The recipe builds `url` with a template.
3. **No posted/created timestamp.** `job_post_info` has only `expiry_time` (null in every
   record sampled). Freshness must come from run-over-run diffing, like the other boards here.
4. **Nested dicts, `name` vs `en_name`.** `city_info.name` / `job_category.name` are `null`;
   the readable values are in `en_name` / `i18n_name`. Mapping `name` would silently produce
   all-null locations.
5. **The site does an IP-geolocation call** (`/api/v1/ip/location`). Default unfiltered search
   returned the global dataset from this US machine, but a region-pinned edge could in theory
   serve different defaults — the `expected_min_jobs` floor is the tripwire for that.
6. **HTML/DOM is a dead end by design:** no embedded JSON islands (`embedded_json: []` in
   report.json), Next.js SPA with utility-class soup — DOM classes are unstable jsx-hash noise.

## Recipe kind chosen and why

`http_json` (the most-preferred kind). The data lives on a public JSON API reproducible with
one static header and a static JSON body; no cookies, no tokens, no browser. `http_html` and
`browser_dom` were not needed — and embedded-JSON extraction is impossible anyway (no islands).

## Fragility

- **Loud failures (good):** dropping/renaming the `website-path` header contract → 400 raises;
  moving `data.job_post_list` → records_path raises; total shrinking below 2000 → raises.
- **Silent-ish risks:**
  - If TikTok splits the portal (e.g. separate `website-path` values per brand/region) the
    endpoint would still 200 but with a subset; `expected_min_jobs=2000` (~53% of today's
    3799) is the guard. Justification: on the site's own oracle today, anything under ~half
    signals a filter/portal regression, not organic shrinkage — this is the exact class of
    failure behind the 3,582-job false-closure incident.
  - The API returns `code` inside a 200 envelope; a future soft error (`code != 0` with empty
    list) would raise via the zero-records guard, but a `code != 0` with a *partial* list is
    conceivable and would only be caught by the floor.
  - Response has no schema versioning; `en_name` fields could move under i18n changes (would
    null out location/department but keep id/title/url flowing).

## Measurements

- Capture wall-seconds: 13.7 (capture.py) + ~35s of httpx/Playwright probes (≈15 polite requests total)
- Replay wall-seconds: **9.2** (4 POSTs of 1000)
- Job count replayed: **3799** unique ids
- Site-claimed total: **3799** (`data.count`) — **100% coverage, zero dedup loss**
- Dollars: **$0**

## SCHEMA GAP

None. The existing schema expresses this site fully — notably because replay.py merges the
offset pagination param into the JSON body for POST entrypoints, which is precisely this
API's contract.

## Files

- Recipe: `scripts/one_off/recipe_spike/recipes/tiktok.json`
- Evidence: `captures/tiktok/report.json`, `captures/tiktok/raw/000.json`
- Probes (throwaway, kept as evidence): `_probe_request.py`, `_probe_httpx.py`,
  `_probe_pagination.py`, `_probe_limit2000.py`, `_inspect_raw.py`
- Replay result: `results/discover-20260805T051431Z.json`
