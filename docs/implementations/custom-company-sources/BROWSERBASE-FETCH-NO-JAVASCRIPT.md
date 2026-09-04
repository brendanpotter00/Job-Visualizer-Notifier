# Browserbase Fetch does not execute JavaScript

**Verdict: Fetch is an HTTP client, not a browser.** On a JS-rendered job board it returns the
shell and none of the jobs. For our use case — "does this URL lead to real postings?" — that
makes it unusable, and our own `httpx` does the same job for free.

## The test

**URL**

```
https://www.atlassian.com/company/careers/all-jobs
```

**Search the response for this exact string**

```
/company/careers/details/
```

| | job-detail links | measured with |
|---|---:|---|
| Real browser | **235** | local Playwright/Chromium, 2026-09-04 |
| Plain HTTP fetch | **0** | `curl -sL` + Chrome UA, same URL, same day |

Zero hits ⇒ no JavaScript ran. Hundreds ⇒ it is a browser and this document is wrong.

**The trap:** the response is *not* empty. Plain fetch returns **146,663 bytes** and the
`<title>` is "Atlassian Jobs: View Listings for Open Positions". A big page with "Jobs" in the
title proves nothing — the `details/` count is the only thing that settles it. Use the path
pattern, not a job title; titles rotate as postings change.

## Reproduce

```bash
# 0 on a non-browser, 235-ish in a real browser
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36'
curl -sL --max-time 30 -A "$UA" https://www.atlassian.com/company/careers/all-jobs \
  | grep -o '/company/careers/details/' | wc -l
```

Run the same URL through Fetch in the dashboard and compare the count.

## Finding more failing URLs

The failing class is **any board that loads its list over XHR after paint.** Recipe:

1. Open the board in Chrome, DevTools → Network → Fetch/XHR. If the jobs arrive in a JSON
   response *after* the document, it will fail Fetch.
2. Pick a URL-path substring unique to a posting (`/details/`, `/job/`, `/jobs/`, `gh_jid=`).
3. Count it in a plain `curl` vs in the browser DOM. A large gap is the bug.

Measured on 2026-09-04, plain fetch vs the same page in a browser:

| board | plain-fetch job links | note |
|---|---:|---|
| `atlassian.com/company/careers/all-jobs` | **0** | 235 in-browser |
| `careers.oracle.com/en/sites/jobsearch/jobs` | **0** | Oracle Recruiting Cloud SPA |
| `github.careers/careers-home/jobs` | 4 | Phenom; partly server-rendered |
| `careers.amd.com/careers-home/jobs` | 1 | Phenom; partly server-rendered |

Note the Phenom rows: partial server-rendering means a naive "has jobs?" check gets a
*small non-zero* number, which is arguably worse than zero — it looks like a pass.

## Why we care

We pick a company's job board out of ~25 search results and need to know which candidate is a
real list. "Fetch it and see if it has jobs" is the obvious check and **it does not work**:
the correct answers for Oracle and Atlassian both show **0** jobs to any non-JS fetch, while
their wrong marketing pages return *more* bytes (51,289 vs 41,863 for Oracle; 330,157 vs
146,541 for Atlassian). Page size is an anti-signal.

**What we do instead:** read the page and take the links it *publishes*. Anchors are in the
server HTML even when the list is not — `oracle.com/careers/` shows zero jobs to a fetch but
links to its real board three times under "Search jobs". See `CAREERS-FALLBACK-POC.md` and
`careers_page_pick.py`.

**Cost note.** A real browser session *would* see the jobs, but that is the metered resource;
one session per candidate × 5 candidates per search is exactly the spend we avoid. Every fetch
in the picker today is plain `httpx` — **zero paid calls**.

## Provenance

- The browser and `curl` counts above: measured directly, 2026-09-04, recorded here.
- An earlier evaluation of `POST /v1/fetch` found it **byte-identical to our own `httpx` on
  15/15 pages and ~2.4× slower**. That is the origin of the "not a browser" claim; the
  Atlassian test above is the single reproducible case to hand a vendor.
- **Not yet run against the Fetch dashboard by us** — the test is written so that result is a
  one-line yes/no. Record it here when someone runs it.
