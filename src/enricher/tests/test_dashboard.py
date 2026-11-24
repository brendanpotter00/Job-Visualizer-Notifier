"""Dashboard JSON API tests.

Mirror the existing suite: the `store` fixture (conftest) is a fresh temp SQLite
Store, injected into the FastAPI app via dependency_overrides so nothing touches
the real data/enricher.db. serve_static=False skips the SPA mount (no build in CI).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from job_enricher import enrich_config as ec
from job_enricher.dashboard import create_app, get_store
from job_enricher.store import HEARTBEAT_KEY


def _client(store) -> TestClient:
    app = create_app(serve_static=False)
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def _seed(store, jid: str, *, source_id: str = "greenhouse", conf: float = 0.9,
          needs_human: bool = False, category: str = "software_engineering") -> None:
    store.enqueue_inbox([{
        "job_listing_id": jid, "source_id": source_id,
        "title": "Senior SWE", "company": "Acme",
        "raw_location": "San Francisco, CA",
        "description_html": "<p>build things</p>",
        "details_json": None, "content_hash": f"h-{source_id}-{jid}",
    }])
    store.record_clean(source_id, jid, "build things")
    store.record_enrichment({
        "job_listing_id": jid, "source_id": source_id,
        "category": category, "level": "senior",
        "level_includes": "[]", "tags": "[]", "locations": "[]",
        "classify_confidence": conf, "classify_reasoning": "looks senior",
        "taxonomy_version": "v1+test", "needs_human": needs_human,
        "classify_model": "sonnet",
    })


def test_health_reports_all_keys(store):
    _seed(store, "1")
    body = _client(store).get("/api/health").json()
    assert set(body) == {
        "inbox", "unsent", "needs_human", "failed_rows", "starved_null_recency",
        "last_heartbeat_at",
        "last_heartbeat_age_s", "stage_timings", "classify_engine", "classify_model",
        "judge_engine", "judge_model", "opencode_model", "latest_tick",
        # BF-10: one edit to collect_health surfaces on cli health AND here.
        "subcategory",
    }
    assert body["inbox"].get("enriched") == 1
    assert body["unsent"] == 1  # enriched-but-unsent row is write-back backlog
    # the engine is what's actually running — must not be dropped by the API the
    # way the Claude-tier model alone would mislead an ollama deployment
    assert body["classify_engine"] == "ollama"
    assert body["judge_engine"] == "ollama"
    assert body["opencode_model"] == "qwen3:32b"


def test_ticks_include_stage_timings_and_drift_flag(store):
    store.start_tick()
    store.bump_tick_counters(classified=10, nulled_facets=6)  # >50% nulled -> drift
    store.record_stage_timing("classify", "2026-01-01T00:00:00+00:00",
                              "2026-01-01T00:00:03+00:00", 3000, item_count=10)
    store.end_tick("ok")
    tick = _client(store).get("/api/ticks").json()["ticks"][0]
    assert tick["drift_suspected"] is True
    assert tick["stage_timings"][0]["stage"] == "classify"


def test_ticks_no_drift_when_below_threshold(store):
    store.start_tick()
    store.bump_tick_counters(classified=4, nulled_facets=4)  # classified < 10
    store.end_tick("ok")
    assert _client(store).get("/api/ticks").json()["ticks"][0]["drift_suspected"] is False


def test_tick_detail_404(store):
    assert _client(store).get("/api/ticks/999").status_code == 404


def test_jobs_filter_needs_human(store):
    _seed(store, "1", needs_human=False)
    _seed(store, "2", needs_human=True)
    body = _client(store).get("/api/jobs", params={"needs_human": True}).json()
    assert body["total"] == 1
    assert body["jobs"][0]["job_listing_id"] == "2"
    assert body["jobs"][0]["needs_human"] == 1


def test_jobs_pagination_reports_total(store):
    for i in range(5):
        _seed(store, str(i))
    body = _client(store).get("/api/jobs", params={"limit": 2}).json()
    assert body["total"] == 5
    assert len(body["jobs"]) == 2
    assert body["limit"] == 2


def test_job_detail_and_404(store):
    _seed(store, "1")
    c = _client(store)
    detail = c.get("/api/job", params={"source_id": "greenhouse",
                                       "job_listing_id": "1"}).json()
    assert detail["category"] == "software_engineering"
    assert detail["clean_description"] == "build things"
    assert c.get("/api/job", params={"source_id": "x",
                                     "job_listing_id": "nope"}).status_code == 404


def test_knobs_get_defaults(store):
    body = _client(store).get("/api/knobs").json()
    assert body["snapshot"]["classify_model"] == "haiku"
    assert body["snapshot"]["classify_engine"] == "ollama"
    assert body["snapshot"]["judge_engine"] == "ollama"
    assert body["snapshot"]["opencode_model"] == "qwen3:32b"
    assert body["snapshot"]["enrich_per_tick_limit"] == 40
    assert "haiku" in body["meta"]["models"]
    assert "ollama" in body["meta"]["engines"]
    assert body["meta"]["enrich_per_tick_limit_bounds"] == [1, 500]
    assert "software_engineering" in body["meta"]["categories"]


def test_knobs_post_persists_to_meta(store):
    c = _client(store)
    out = c.post("/api/knobs", json={"key": "classify_model", "value": "haiku"})
    assert out.status_code == 200
    assert out.json()["snapshot"]["classify_model"] == "haiku"
    # proves the POST hit the same meta table the CLI/tick pipeline reads
    assert ec.get_classify_model(store) == "haiku"


def test_knobs_post_bad_key_400(store):
    assert _client(store).post(
        "/api/knobs", json={"key": "nope", "value": 1}
    ).status_code == 400


def test_knobs_post_bad_value_400(store):
    assert _client(store).post(
        "/api/knobs", json={"key": "classify_model", "value": "gpt"}
    ).status_code == 400


def test_knobs_post_clamps_out_of_range(store):
    out = _client(store).post("/api/knobs",
                              json={"key": "classify_batch_size", "value": 999})
    assert out.status_code == 200
    assert out.json()["snapshot"]["classify_batch_size"] == 10  # ec clamps to bound


def test_knobs_post_judge_toggle_bool_coercion(store):
    c = _client(store)
    assert c.post("/api/knobs", json={"key": "judge_enabled", "value": "off"}
                  ).json()["snapshot"]["judge_enabled"] is False
    assert c.post("/api/knobs", json={"key": "judge_enabled", "value": True}
                  ).json()["snapshot"]["judge_enabled"] is True


# Each _KNOB_SETTERS lambda is a single line, so statement coverage marks it
# "hit" at import — these actually exercise the coercion + ec.set_* per knob.
@pytest.mark.parametrize(
    "key, value, getter, expected",
    [
        ("classify_fan_out", 5, ec.get_classify_fan_out, 5),
        ("judge_model", "opus", ec.get_judge_model, "opus"),
        ("judge_scope", "all", ec.get_judge_scope, "all"),
        ("judge_human_floor", 0.4, ec.get_judge_human_floor, 0.4),
        ("judge_confidence_ceiling", 0.5, ec.get_judge_confidence_ceiling, 0.5),
    ],
)
def test_knobs_post_each_knob_persists(store, key, value, getter, expected):
    out = _client(store).post("/api/knobs", json={"key": key, "value": value})
    assert out.status_code == 200
    assert out.json()["snapshot"][key] == expected
    # persisted to the same meta table the tick pipeline reads back
    assert getter(store) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("on", True), ("1", True), ("true", True), ("yes", True),
     ("", False), ("no", False)],
)
def test_knobs_bool_truthy_strings(store, value, expected):
    out = _client(store).post("/api/knobs", json={"key": "judge_enabled", "value": value})
    assert out.status_code == 200
    assert out.json()["snapshot"]["judge_enabled"] is expected


def test_knobs_post_type_error_400(store):
    # int(None) raises TypeError (not ValueError) -> still a 400, never a 500
    out = _client(store).post("/api/knobs",
                              json={"key": "classify_batch_size", "value": None})
    assert out.status_code == 400


def test_knobs_taxonomy_missing(store, monkeypatch):
    # a checkout without SKILL.md makes taxonomy_version() raise OSError; the
    # panel must degrade to taxonomy_version=None, not 500.
    import job_enricher.taxonomy as tax_mod

    def _boom() -> str:
        raise OSError("no SKILL.md in this checkout")

    monkeypatch.setattr(tax_mod, "taxonomy_version", _boom)
    resp = _client(store).get("/api/knobs")
    assert resp.status_code == 200
    assert resp.json()["meta"]["taxonomy_version"] is None


def test_tick_detail_ok(store):
    tid = store.start_tick()
    store.bump_tick_counters(classified=10, nulled_facets=6)  # >50% nulled -> drift
    store.record_stage_timing("classify", "2026-01-01T00:00:00+00:00",
                              "2026-01-01T00:00:03+00:00", 3000, item_count=10)
    store.end_tick("ok")
    body = _client(store).get(f"/api/ticks/{tid}").json()
    assert body["id"] == tid
    assert body["stage_timings"][0]["stage"] == "classify"
    assert body["drift_suspected"] is True


def test_ticks_limit_truncates(store):
    ids = []
    for _ in range(3):
        ids.append(store.start_tick())
        store.end_tick("ok")
    body = _client(store).get("/api/ticks", params={"limit": 1}).json()
    assert len(body["ticks"]) == 1
    assert body["ticks"][0]["id"] == max(ids)  # newest first


def test_health_heartbeat_age(store):
    _seed(store, "1")
    hb = datetime.now(timezone.utc).isoformat()
    store.set_meta(HEARTBEAT_KEY, hb)
    body = _client(store).get("/api/health").json()
    assert body["last_heartbeat_at"] == hb
    age = body["last_heartbeat_age_s"]
    assert age is not None and 0 <= age < 60


def test_health_heartbeat_malformed(store):
    store.set_meta(HEARTBEAT_KEY, "not-a-date")
    body = _client(store).get("/api/health").json()
    assert body["last_heartbeat_at"] == "not-a-date"
    assert body["last_heartbeat_age_s"] is None  # unparseable -> None, not a 500


def test_jobs_filter_status(store):
    _seed(store, "1")  # stays 'enriched'
    _seed(store, "2")
    store.mark_sent([("greenhouse", "2")])  # -> 'sent'
    body = _client(store).get("/api/jobs", params={"status": "sent"}).json()
    assert body["total"] == 1
    assert body["jobs"][0]["job_listing_id"] == "2"
    assert body["jobs"][0]["status"] == "sent"


def test_jobs_offset(store):
    for i in range(5):
        _seed(store, str(i))
    c = _client(store)
    page1 = c.get("/api/jobs", params={"limit": 2, "offset": 0}).json()
    page2 = c.get("/api/jobs", params={"limit": 2, "offset": 2}).json()
    assert page2["offset"] == 2
    assert page1["total"] == page2["total"] == 5
    ids1 = {j["job_listing_id"] for j in page1["jobs"]}
    ids2 = {j["job_listing_id"] for j in page2["jobs"]}
    assert len(ids2) == 2 and ids1.isdisjoint(ids2)  # distinct page of rows


def test_jobs_lists_unenriched_job_via_left_join(store):
    """A claimed/cleaned job with NO enrichment row must still surface via the
    LEFT JOIN (an INNER JOIN would silently hide every un-enriched job). Its
    enrichment-side columns are null and needs_human COALESCEs to 0."""
    store.enqueue_inbox([{
        "job_listing_id": "u1", "source_id": "greenhouse",
        "title": "Unenriched SWE", "company": "Acme",
        "raw_location": "Remote",
        "description_html": "<p>tbd</p>",
        "details_json": None, "content_hash": "h-greenhouse-u1",
    }])
    store.record_clean("greenhouse", "u1", "tbd")  # cleaned, never enriched
    body = _client(store).get("/api/jobs").json()
    assert body["total"] == 1
    row = body["jobs"][0]
    assert row["job_listing_id"] == "u1"
    assert row["status"] == "cleaned"
    assert row["needs_human"] == 0        # COALESCE(e.needs_human, 0)
    assert row["category"] is None        # no enrichment row -> null facets
    assert row["level"] is None
    assert row["classify_confidence"] is None


def test_spa_missing_dist_returns_503(monkeypatch, tmp_path):
    """serve_static=True with no built dist/ -> the SPA catch-all serves the
    'build me' 503, not a 200/500."""
    import job_enricher.dashboard as dash

    monkeypatch.setattr(dash, "DIST", tmp_path / "nonexistent-dist")
    resp = TestClient(dash.create_app(serve_static=True)).get("/")
    assert resp.status_code == 503
    assert "Dashboard not built" in resp.text


def test_spa_serves_file_inside_dist_and_blocks_traversal(monkeypatch, tmp_path):
    """The catch-all serves a real file that resolves inside dist, but the
    `dist in candidate.parents` guard must stop an encoded ../../ from escaping
    dist to a sibling secret (falls back to index.html, never leaks the file)."""
    import job_enricher.dashboard as dash

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>spa-shell")
    (dist / "favicon.ico").write_text("icon-bytes")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")  # sibling of dist, must never be served

    monkeypatch.setattr(dash, "DIST", dist)
    client = TestClient(dash.create_app(serve_static=True))

    # a real top-level file inside dist is served through the guarded branch
    ok = client.get("/favicon.ico")
    assert ok.status_code == 200
    assert ok.text == "icon-bytes"

    # an encoded traversal must NOT reach the sibling secret; the guard rejects
    # the escaped candidate and the SPA falls back to index.html
    escaped = client.get("/%2e%2e%2f%2e%2e%2fsecret.txt")
    assert "TOP SECRET" not in escaped.text
    assert escaped.status_code == 200
    assert "spa-shell" in escaped.text


def test_knob_snapshot_and_setter_allowlist_agree(store):
    """Contract guard: every knob in the GET snapshot must have a matching POST
    setter (and vice-versa). A drift here ships a control that renders but whose
    save 400s ('unknown knob'), or a snapshot key with no editor."""
    from job_enricher.dashboard import _KNOB_SETTERS
    from job_enricher.enrich_config import config_snapshot

    assert set(config_snapshot(store)) == set(_KNOB_SETTERS)


# ---- OPS-4 / BF-10: the backfill lane on the dashboard ----------------------
def test_health_carries_the_subcategory_block(store):
    _seed(store, "1")
    block = _client(store).get("/api/health").json()["subcategory"]
    for key in (
        "eligible", "labelled", "empty", "stuck", "total_swe",
        "local_coverage_pct", "shipped_coverage_pct", "pending_push",
        "last_label_run", "last_push_run",
    ):
        assert key in block


def test_every_new_backfill_knob_is_settable_from_the_dashboard(store):
    """⚠ _KNOB_SETTERS is the dashboard's ENTIRE write surface — a knob missing
    from it cannot be toggled at all."""
    client = _client(store)
    for key, value in (
        ("backfill_enabled", True),
        ("backfill_batch_size", 8),
        ("backfill_max_attempts", 4),
        ("subcategory_push_batch", 100),
        ("subcategory_push_duty_pct", 10),
        ("subcategory_push_max_seconds", 1800),
    ):
        resp = client.post("/api/knobs", json={"key": key, "value": value})
        assert resp.status_code == 200, (key, resp.text)
    snap = client.get("/api/knobs").json()["snapshot"]
    assert snap["backfill_enabled"] is True
    assert snap["subcategory_push_batch"] == 100


def test_a_bad_backfill_knob_value_is_a_400_not_a_500(store):
    resp = _client(store).post(
        "/api/knobs", json={"key": "backfill_batch_size", "value": "not-an-int"}
    )
    assert resp.status_code == 400


def test_knob_meta_lists_all_seventeen_subcategory_slugs(store):
    from job_enricher import taxonomy as tax

    meta = _client(store).get("/api/knobs").json().get("meta", {})
    assert meta.get("subcategories") == sorted(tax.SUBCATEGORIES)
    assert len(meta["subcategories"]) == 17


def test_the_swe_without_subcategories_filter_returns_only_that_cohort(store):
    """OPS-4's Jobs-panel filter: the backfill queue plus the TERMINAL [] rows."""
    from job_enricher.store import now_iso

    with store.connect() as c:
        for jid, cat, subs in (
            ("queued", "software_engineering", None),
            ("empty", "software_engineering", "[]"),
            ("labelled", "software_engineering", '["backend"]'),
            ("notswe", "growth", None),
        ):
            c.execute(
                "INSERT INTO inbox (job_listing_id, source_id, title, company, "
                "raw_location, content_hash, claimed_at, status) "
                "VALUES (?, 'gh', 'T', 'Acme', 'SF', ?, ?, 'sent')",
                (jid, f"h-{jid}", now_iso()),
            )
            c.execute(
                "INSERT INTO enrichments (job_listing_id, source_id, category, "
                "subcategories, enriched_at) VALUES (?, 'gh', ?, ?, ?)",
                (jid, cat, subs, now_iso()),
            )
    body = _client(store).get("/api/jobs?swe_without_subcategories=true").json()
    assert {j["job_listing_id"] for j in body["jobs"]} == {"queued", "empty"}
    assert body["total"] == 2
