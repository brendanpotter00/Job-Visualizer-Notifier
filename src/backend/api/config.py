"""Application configuration via environment variables."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/jobscraper"

    # Scraper settings
    scraper_interval_hours: int = Field(default=1, gt=0)
    # NOTE: SCRAPER_COMPANIES overrides this default if set. It is currently
    # NOT set in Railway prod (verified 2026-08-10), so this literal is what
    # production actually runs — adding a scraper here does enable it on the
    # next deploy. If someone later sets the env var, it silently wins and this
    # line stops mattering; check Railway before assuming a scraper is live.
    scraper_companies: str = "apple,google,microsoft,amazon,tiktok"
    scraper_detail_scrape: bool = True
    scraper_timeout_minutes: int = Field(default=90, gt=0)
    scraper_scripts_path: str = "../../scripts"
    scraper_python_path: str = "python3"

    # Database pool
    db_pool_min: int = Field(default=1, ge=1, le=20)
    db_pool_max: int = Field(default=15, ge=1, le=50)
    db_pool_timeout: int = Field(default=5, ge=1, le=30)

    @model_validator(mode="after")
    def validate_pool_bounds(self) -> "Settings":
        if self.db_pool_min > self.db_pool_max:
            raise ValueError(
                f"db_pool_min ({self.db_pool_min}) must not exceed db_pool_max ({self.db_pool_max})"
            )
        return self

    # DB watchdog (services/db_watchdog.py): exits the process after ~5-6
    # sustained minutes of DB unreachability so Railway restarts the
    # container. Probe every 30s, 15s hard deadline per probe.
    db_watchdog_enabled: bool = True
    db_watchdog_probe_interval_seconds: float = Field(default=30.0, gt=0)
    db_watchdog_probe_deadline_seconds: float = Field(default=15.0, gt=0)
    db_watchdog_failure_window_seconds: float = Field(default=300.0, gt=0)

    # Boot-time budget for retrying startup migrations through DB-connectivity
    # failures (migrations.apply_alembic_migrations_with_retry). Keeps a
    # watchdog-triggered restart during a long DB outage from crash-looping
    # in seconds and burning railway.toml's restartPolicyMaxRetries budget.
    # In practice the watchdog window (~6 min) caps it. Set 0 to fail fast
    # when booting locally without Postgres.
    db_boot_connect_retry_seconds: float = Field(default=600.0, ge=0)

    # Worker watchdog (services/worker_watchdog.py): exits the process when the
    # Procrastinate worker stops advancing worker_heartbeats.at while the DB is
    # reachable, so Railway restarts the container. Catches a *wedged* executor
    # (2026-08-29 incident: run_worker_async hung mid-drain and never returned,
    # so the lifespan supervisor never restarted it — 61h silent outage). The
    # heartbeat task fires every 5 min; stale_after 15 min = 3 missed beats, a
    # margin over a legitimately busy worker (jobs are capped at 120s). The
    # window requires the staleness to persist before exiting. startup_grace
    # gives a freshly-restarted worker time to write its first beat before a
    # pre-restart (stale) row is judged. Unreachable DB is db_watchdog's job,
    # not this one's.
    worker_watchdog_enabled: bool = True
    worker_watchdog_probe_interval_seconds: float = Field(default=60.0, gt=0)
    worker_watchdog_stale_after_seconds: float = Field(default=900.0, gt=0)
    worker_watchdog_failure_window_seconds: float = Field(default=120.0, gt=0)
    worker_watchdog_startup_grace_seconds: float = Field(default=600.0, ge=0)

    # Auth0 authentication
    auth0_domain: str | None = None
    auth0_audience: str | None = None

    # Google One Tap authentication
    google_client_id: str | None = None

    # Internal API key: shared secret between the Vercel serverless proxies
    # and this backend. When set, the require_internal_key middleware rejects
    # any request that doesn't present a matching X-Internal-Key header.
    # When unset (local dev), the middleware allows all requests through and
    # logs a startup warning.
    internal_api_key: str | None = None

    # Anthropic API key for location normalization (Tier 2 — Claude Haiku).
    # Read from the ANTHROPIC_API_KEY env var. When unset, the normalize
    # pipeline must degrade gracefully (later units): Tier 1 / schema / admin
    # endpoints operate normally and rows simply stay unnormalized. Plain
    # str|None to match internal_api_key (NOT SecretStr).
    anthropic_api_key: str | None = None

    # External enrichment (job-enricher pull integration). All default OFF. The
    # flag gates ONLY /pending: with it off, /pending hands out nothing, so no
    # rows are ever claimed/enriched and the cloud-Haiku location pipeline remains
    # the floor. (/results, /sample, /health are NOT flag-gated — they run
    # regardless; already-enriched facets persist even if the flag is later off.)
    # The laptop authenticates with the existing internal_api_key; JVN never
    # calls the laptop (pull model).
    enrichment_use_external: bool = False          # master flag; gates /pending
    # Stale-claim reclaim window. MUST exceed a full enricher tick (one /pending →
    # classify → /results batch round-trip); otherwise an in-flight batch's rows
    # are reclaimed mid-flight and double-handed (wasting laptop tokens; only made
    # safe by the idempotent /results upsert). 240 = the enricher's 3h tick
    # watchdog (ENRICH_TICK_TIMEOUT_SECS) + an hour of slack — the old 15m
    # default guaranteed false stale_claims alerts during every normal long
    # tick and mid-flight reclaims on any tick past 15 minutes.
    enrichment_claim_ttl_minutes: int = Field(default=240, gt=0)
    # If True, /results HOLDS judge-flagged rows as 'needs_human' (keyed on
    # judge.needs_human) instead of publishing them 'done'. Rows are held, NOT
    # dropped — the audit payload is still written either way.
    enrichment_require_judge_pass: bool = False
    # If True, /pending drops the "row must have a description" guard and claims
    # description-less rows too (workday_api/eightfold_api capture no description
    # under any known key). The enricher classifies these title-only at low
    # confidence — an interim stopgap until their scrapers capture real text.
    # Default OFF: flip ON only AFTER the enricher's title-only handling ships,
    # so description-less rows aren't classified at full confidence in the gap.
    enrichment_claim_without_description: bool = False
    # Share of each /pending batch RESERVED for custom (user-added) companies.
    # The claim orders first_seen_at DESC. That used to mean a freshly-added custom
    # board's rows were unconditionally the NEWEST in the table and sorted to the
    # FRONT of the queue. It no longer does: first_seen_at is now seeded from the
    # board's own POSTED DATE when it publishes one, so a board carrying real
    # posting dates inserts rows dated months back and those sort to the BACK.
    #
    # The reservation is worth strictly MORE after that change, not less, because
    # both directions are now possible and both are bad. A dateless board (or one
    # posting today) still front-runs every published company exactly as before —
    # one user pasting one 47k-job careers URL holding ~100% of the claim for years.
    # A board with real dates has the opposite problem: its rows land behind a
    # 16,201-row published backlog that (at one local ollama worker) does not drain,
    # so without a reserved slice they would never be claimed at all. A floor that
    # is also a ceiling is what makes neither of those depend on what dates the
    # board happens to publish. 10% is deliberately the smallest
    # number that is visibly not zero: the pipeline (one local ollama worker) is
    # saturated, so every point above this comes straight out of a published
    # backlog that already never drains. 0 disables custom claiming entirely
    # (kill switch); 100 hands the whole batch to custom.
    enrichment_custom_share_pct: int = Field(default=10, ge=0, le=100)
    # Per-custom-company eligibility cap: only a company's newest N *unclaimed*
    # OPEN rows compete in the custom slice. It bounds how many of ONE board's
    # rows can enter a single claim, which is what stops a mega-board's deep
    # tier-0 history (old "intern" titles buried 20k rows down) from outranking
    # every other company's fresh postings. Unclaimed, not absolute: the window
    # SLIDES as rows are enriched, so nothing is walled off forever — see
    # routers/internal_enrichment.py.
    enrichment_custom_per_company_cap: int = Field(default=500, gt=0)

    # Custom company sources (E7). Gates the whole user-pasted-careers-URL
    # feature: today only ``POST /api/companies/resolve`` (which 503s with the
    # flag off), later the recipe runtime and the self-serve add path. Default
    # OFF so the code can ship dark; rollback is flipping this back to False.
    # NOTE: ``Settings.model_config`` sets ``extra="ignore"``, so a typo'd env
    # var name would silently leave this False — the name is pinned by
    # ``api/tests/test_companies_resolve_endpoint.py``.
    custom_company_sources_enabled: bool = False

    # Custom company DISCOVERY (E7 — the capture pivot; THE single discovery flag).
    # Distinct from ``custom_company_sources_enabled`` above: the (free) ATS add path
    # can ship while the one-time browser+LLM capture stays dark. A non-ATS URL only
    # enqueues a ``discover_custom_company`` task (one Chromium session + ONE Claude
    # Haiku call, well under a cent per add) when BOTH this and the parent flag are on;
    # with this off the non-ATS branch keeps returning today's 422 ``unsupported``.
    #
    # It is deliberately the ONLY discovery gate. The retired Stagehand tier had a
    # second per-transport switch (``browser_agent_enabled``) and the pair was a trap:
    # one flag alone produced a misleading "No supported ATS board" 422 with no hint
    # that the other was off. Enforced in three places that MUST move together — the
    # add-flow router, this task's defence-in-depth re-check, and the nightly
    # ``browser_fetch`` replay branch — which also makes it the fleet-wide stop for the
    # whole own-Chromium/SSRF surface. Default OFF so spend cannot happen until it is
    # deliberately flipped on.
    custom_company_discovery_enabled: bool = False

    # Browserbase (E7 capture pivot) — an OPTIONAL discovery-time upgrade, never the
    # default and never used for the nightly replay. Discovery captures with OUR OWN
    # headless Chromium because Browserbase bills per browser-hour; the two things it
    # buys are stealth/residential IPs for a bot-walled board and the hosted live-view
    # URL the discovery-progress UI embeds. Credentials read from BROWSERBASE_API_KEY /
    # BROWSERBASE_PROJECT_ID; the LLM tokens bill to ``anthropic_api_key`` (our key).
    browserbase_api_key: str | None = None
    browserbase_project_id: str | None = None
    # The opt-in. With this OFF (default) — or with either credential unset —
    # ``network_capture`` launches our own Chromium and never touches Browserbase.
    # Turning it on cannot make discovery fail: a session-create error degrades back to
    # our own browser rather than refusing a board we could have read for free.
    capture_use_browserbase: bool = False

    # Type a company NAME instead of pasting a URL. One Browserbase Search call
    # per attempt (~$0.007, and the plan includes 1,000 free), then our own free
    # deterministic scoring — no model call, no browser. Independent of
    # ``capture_use_browserbase``: this uses the Search API, discovery uses
    # Browsers, and they are separately priced products. Default OFF so no spend
    # can happen until it is deliberately flipped on; with it off the add box is
    # exactly as URL-only as it was before.
    company_name_search_enabled: bool = False

    # LOCAL DEVELOPMENT ONLY — the destructive custom-company reset
    # (``POST /api/users/dev-reset``, ``services/dev_reset.py``). It deletes every
    # ``visibility='user'`` company the caller owns, their jobs, and their
    # ``company_add_attempts`` audit — which is also the monthly-quota counter, so a
    # reset gives the adds back. That is the whole point: without it the add flow
    # cannot be re-tested, because "you already track this" changes the behaviour on
    # every attempt after the first.
    #
    # OFF means the router is NOT REGISTERED (``main.py`` skips ``include_router``),
    # so the path 404s exactly like a path that does not exist — never a 403, which
    # would advertise that the endpoint is there and merely refusing.
    #
    # THIS FLAG IS NOT THE REAL GUARD. A flag is one env var away from being wrong on
    # the wrong machine, so the endpoint ALSO re-derives, at call time and independent
    # of this setting, that ``database_url`` points at a loopback host
    # (``dev_reset.assert_local_database``) and refuses otherwise. Two independent
    # mistakes are required to delete anything that is not on someone's laptop.
    dev_reset_enabled: bool = False

    # PostHog analytics
    posthog_project_token: str | None = None
    posthog_host: str = "https://us.i.posthog.com"

    # Public feedback endpoint rate limit (per client IP, sliding window).
    # Defaults are generous for a human but hostile to a script: 5 submissions
    # per 60s. Enforced in-process by services/rate_limit.py — see that module
    # for why an in-memory limiter is appropriate here.
    feedback_rate_limit_max: int = Field(default=5, gt=0)
    feedback_rate_limit_window_seconds: int = Field(default=60, gt=0)

    # POST /api/companies/resolve rate limit (per authenticated user, sliding
    # window). Unlike feedback this route is authenticated, so the key is the
    # user id rather than a spoofable client IP. The limit is not about spam: one
    # call fans out to as many as 36 outbound requests and occupies a slot in
    # url_guard's 4-thread DNS pool for as long as a hostile host's resolver
    # cares to stall, so an unlimited authenticated caller is a self-inflicted
    # denial of service on the whole process. 10/60s is far more than the paste-
    # one-URL-and-look-at-it flow needs.
    resolve_rate_limit_max: int = Field(default=10, gt=0)
    resolve_rate_limit_window_seconds: int = Field(default=60, gt=0)

    # POST /api/users/companies BURST limit (per authenticated user, sliding
    # window) — deliberately the same 10/60s shape as the resolve pair above.
    #
    # THIS ENDPOINT, not just resolve. The UI happens to call resolve first, so
    # the front door looked throttled; a bearer token replayed straight at the
    # add endpoint skipped it entirely. This is the route that starts a headless
    # Chromium session and an LLM call, so it is the one that had to be bounded.
    #
    # In-memory and per-process (see services/rate_limit.py), which is fine here
    # BECAUSE it is only a burst smoother: the real spend guard is the monthly cap
    # below, which lives in Postgres and survives a deploy.
    user_company_add_rate_limit_max: int = Field(default=10, gt=0)
    user_company_add_rate_limit_window_seconds: int = Field(default=60, gt=0)

    # PATCH /api/users/companies/{id} — the rename. A SEPARATE, much looser limit,
    # and deliberately not the add pair above.
    #
    # A rename is one UPDATE. It opens no browser, makes no outbound request and
    # spends no LLM call, so charging it against either of the add path's budgets
    # would be wrong twice over: the 10/60s burst limiter exists to bound Chromium
    # sessions, and the monthly cap is a SPEND guard defined as "URLs we acted on" —
    # making a user pay one of their twenty adds to fix a typo would be absurd.
    #
    # It is still an authenticated write, so it is not unbounded. 30/60s is an order
    # of magnitude above any human's editing rate (a user correcting one name presses
    # save once) while bounding a replayed token to a harmless trickle.
    user_company_rename_rate_limit_max: int = Field(default=30, gt=0)
    user_company_rename_rate_limit_window_seconds: int = Field(default=60, gt=0)

    # How many URLs one user may submit to POST /api/users/companies per CALENDAR
    # MONTH (UTC — resets at midnight on the 1st). Every submission counts: a
    # success, a refusal, and a board that turns out to be one we already publish.
    # Deleting a company does NOT give a slot back, which is what makes the cap a
    # real spend guard rather than a cap on how many boards you hold at once.
    #
    # THE NUMBER IS THE NUMBER OF ADDS ALLOWED. 0 allows NONE — there is no sentinel
    # here, because you should not have to understand the business context to know
    # what zero means. ``ge=0`` stays so 0 remains legal and meaningful: it is a
    # genuine per-user kill switch, one env var that stops every add without a deploy.
    #
    # EVERY MISCONFIGURATION FAILS CLOSED, and that is the point.
    # ``Settings.model_config`` sets ``extra="ignore"``, so a typo'd env var NAME is
    # silently dropped and this compiled-in 20 stands — the limit stays ON, whereas an
    # ``..._ENABLED=false``-shaped flag would fail OPEN on the same typo. And a typo'd
    # VALUE that lands on 0 (a bad template, an empty string coerced to an int) now
    # blocks adds; it used to grant every signed-in user unbounded browser + LLM spend.
    #
    # Local dev gets its freedom from a large number (CUSTOM_COMPANY_MONTHLY_ADD_LIMIT
    # =10000 in .env.local), never from 0. The default is pinned by a test, and a boot
    # at 0 logs a startup WARNING (``services/add_quota.warn_if_adds_disabled``).
    custom_company_monthly_add_limit: int = Field(default=20, ge=0)

    # Server
    port: int = 8080
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"

    @property
    def companies_list(self) -> list[str]:
        return [c.strip() for c in self.scraper_companies.split(",") if c.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": (".env", ".env.local"), "extra": "ignore"}


settings = Settings()
