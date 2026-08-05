# Browserbase comparison arm (optional)

`capture_browserbase.py` reruns a `capture.py` discovery pass through a **Browserbase cloud browser** (Stagehand SDK + Playwright-over-CDP) to measure whether a cloud IP gets bot-walled where your local IP does not — and vice-versa. Without credentials it prints "no Browserbase credentials — skipping cloud arm" and exits 0.

## Enable it (the only remaining step)

1. Sign up for the **free** plan at [browserbase.com](https://www.browserbase.com) — do not pick a paid plan.
2. Grab your API key and Project ID from [browserbase.com/settings](https://www.browserbase.com/settings).
3. Add both to the repo root `.env.local` (the script also reads the plain environment):

   ```
   BROWSERBASE_API_KEY=bb_...
   BROWSERBASE_PROJECT_ID=...
   ```

4. Verify with `browse cloud projects list` (CLI `browse/0.9.6` is installed globally). Optional: `MODEL_API_KEY` — only needed if session start ever demands it; this script makes zero AI calls.

## Free-tier limits and how the script respects them

The free plan allots **1 browser-hour and 3 agent calls per month**. The script makes **no** act/extract/agent calls (agent quota untouched), explicitly ends every session, asks Browserbase to hard-kill the session server-side after 300 s as a crash guard, and records actual consumption in the report (`browser_seconds` + `free_tier_note`). A typical capture uses ~1–2 of your 60 monthly minutes.

## Run the comparison

```bash
cd scripts/one_off/recipe_spike
.venv/bin/python capture.py             --target amazon --url "https://www.amazon.jobs/en/search?..."   # local arm  → captures/amazon/report.json
.venv/bin/python capture_browserbase.py --target amazon --url "https://www.amazon.jobs/en/search?..."   # cloud arm  → captures/amazon/report_browserbase.json
diff <(jq . captures/amazon/report.json) <(jq . captures/amazon/report_browserbase.json)
```

Same report structure on both sides (cloud raw artifacts land in `captures/<target>/browserbase/`). SDK: `stagehand` 3.22.0 in the spike venv (`.venv`, Python 3.13) — never the repo's main `.venv`.
