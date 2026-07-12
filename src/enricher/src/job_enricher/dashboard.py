"""LOCAL read+edit dashboard (FastAPI).

SEPARATE from server.py (the HMAC inbound edge): this app edits runtime knobs
over an UNAUTHENTICATED endpoint, so its CLI launcher defaults the bind to
127.0.0.1 and REFUSES a non-loopback --host unless --allow-remote is passed
(see cli._cmd_dashboard). Even with --allow-remote it must NEVER be placed
behind the Cloudflare tunnel — an EDGE_ENABLED=1 setup must not expose the knob
editor.

It reads the local SQLite store (WAL: concurrent reads are safe while a tick
writes) and can edit the runtime knobs through the same validated ec.set_*
setters the CLI uses. Untrusted scraped job text (title/company/description) is
returned as plain JSON data; the React client renders it through JSX/DataGrid
cells, which auto-escape — the server never emits it as HTML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from job_enricher import enrich_config as ec
from job_enricher import taxonomy as tax
from job_enricher.health import collect_health
from job_enricher.metrics import drift_suspected
from job_enricher.store import REPO_ROOT, Store

DIST = REPO_ROOT / "dashboard" / "dist"


def get_store() -> Store:
    """Store provider — overridden via app.dependency_overrides in tests."""
    return Store()


# --- knob editing -----------------------------------------------------------
# Allowlist keyed on config_snapshot() names. Each entry coerces the incoming
# JSON value then calls the matching validated ec.set_* (which clamps/validates
# and persists to the meta table). A bad key or a ValueError/TypeError from the
# setter becomes a 400 — never a 500, never an un-validated write.
def _coerce_bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "on", "yes")
    return bool(v)


_KNOB_SETTERS = {
    "classify_engine": lambda s, v: ec.set_classify_engine(s, str(v)),
    "classify_model": lambda s, v: ec.set_classify_model(s, str(v)),
    "classify_batch_size": lambda s, v: ec.set_classify_batch_size(s, int(v)),
    "classify_fan_out": lambda s, v: ec.set_classify_fan_out(s, int(v)),
    "judge_enabled": lambda s, v: ec.set_judge_enabled(s, _coerce_bool(v)),
    "judge_engine": lambda s, v: ec.set_judge_engine(s, str(v)),
    "judge_model": lambda s, v: ec.set_judge_model(s, str(v)),
    "judge_human_floor": lambda s, v: ec.set_judge_human_floor(s, float(v)),
    "judge_scope": lambda s, v: ec.set_judge_scope(s, str(v)),
    "judge_confidence_ceiling": lambda s, v: ec.set_judge_confidence_ceiling(s, float(v)),
    "opencode_model": lambda s, v: ec.set_opencode_model(s, str(v)),
    "enrich_per_tick_limit": lambda s, v: ec.set_enrich_per_tick_limit(s, int(v)),
}


class KnobUpdate(BaseModel):
    key: str
    value: Any  # bool|int|float|str — validated by the per-knob setter


def _tick_view(store: Store, tick: dict[str, Any]) -> dict[str, Any]:
    """A ticks row plus its per-stage timings and the drift-circuit-breaker
    verdict (drift_suspected reads classified/nulled_facets straight off the row)."""
    view = dict(tick)
    view["stage_timings"] = store.stage_timings_for_tick(int(tick["id"]))
    view["drift_suspected"] = drift_suspected(tick)
    return view


def create_app(serve_static: bool | None = None) -> FastAPI:
    """Build the dashboard app. serve_static defaults to the DASHBOARD_SERVE_STATIC
    env (on unless '0'); tests pass serve_static=False to skip the SPA mount."""
    if serve_static is None:
        serve_static = os.environ.get("DASHBOARD_SERVE_STATIC", "1") != "0"
    app = FastAPI(title="job-enricher dashboard")

    @app.get("/api/health")
    def health(store: Store = Depends(get_store)) -> dict[str, Any]:
        return collect_health(store)

    @app.get("/api/ticks")
    def ticks(
        limit: int = Query(50, ge=1, le=200),
        store: Store = Depends(get_store),
    ) -> dict[str, Any]:
        return {"ticks": [_tick_view(store, t) for t in store.recent_ticks(limit)]}

    @app.get("/api/ticks/{tick_id}")
    def tick(tick_id: int, store: Store = Depends(get_store)) -> dict[str, Any]:
        row = store.get_tick(tick_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no such tick")
        return _tick_view(store, row)

    @app.get("/api/jobs")
    def jobs(
        status: str | None = None,
        needs_human: bool | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        store: Store = Depends(get_store),
    ) -> dict[str, Any]:
        rows, total = store.list_jobs(
            status=status, needs_human=needs_human, limit=limit, offset=offset
        )
        return {"jobs": rows, "total": total, "limit": limit, "offset": offset}

    @app.get("/api/job")
    def job(
        source_id: str,
        job_listing_id: str,
        store: Store = Depends(get_store),
    ) -> dict[str, Any]:
        row = store.job_detail(source_id, job_listing_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no such job")
        return row

    @app.get("/api/knobs")
    def knobs(store: Store = Depends(get_store)) -> dict[str, Any]:
        try:
            tv: str | None = tax.taxonomy_version()
        except OSError:
            tv = None  # SKILL.md not present in this checkout — don't 500 the panel
        return {
            "snapshot": ec.config_snapshot(store),
            "meta": {
                "models": list(ec.MODEL_CHOICES),
                "engines": list(ec.ENGINE_CHOICES),
                "judge_scopes": list(ec.JUDGE_SCOPE_CHOICES),
                "classify_batch_bounds": list(ec.CLASSIFY_BATCH_BOUNDS),
                "classify_fanout_bounds": list(ec.CLASSIFY_FANOUT_BOUNDS),
                "enrich_per_tick_limit_bounds": list(ec.ENRICH_PER_TICK_LIMIT_BOUNDS),
                "categories": sorted(tax.CATEGORIES),
                "levels": sorted(tax.LEVELS),
                "taxonomy_version": tv,
            },
        }

    @app.post("/api/knobs")
    def set_knob(
        update: KnobUpdate,
        store: Store = Depends(get_store),
    ) -> dict[str, Any]:
        setter = _KNOB_SETTERS.get(update.key)
        if setter is None:
            raise HTTPException(status_code=400, detail=f"unknown knob {update.key!r}")
        try:
            setter(store, update.value)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": ec.config_snapshot(store)}

    if serve_static:
        _mount_spa(app)
    return app


def _missing_dist_html() -> str:
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>job-enricher dashboard</title>"
        "<h1>Dashboard not built</h1>"
        "<p>Build the front-end once, then reload:</p>"
        "<pre>cd dashboard &amp;&amp; npm install &amp;&amp; npm run build</pre>"
        "<p>The JSON API under <code>/api</code> is already live.</p>"
    )


def _mount_spa(app: FastAPI) -> None:
    """Serve the built SPA. API routes are registered first, so /api/* always
    wins. The catch-all serves a real built file when one exists (assets), else
    index.html (refresh-safety for the tab-state SPA), else a 'build me' message."""
    dist = DIST.resolve()
    index = dist / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Any:
        if full_path:
            candidate = (dist / full_path).resolve()
            # path-traversal guard: only serve files that resolve inside dist
            if candidate.is_file() and dist in candidate.parents:
                return FileResponse(candidate)
        if index.exists():
            return FileResponse(index)
        return HTMLResponse(_missing_dist_html(), status_code=503)


# Module-level target for uvicorn.run("job_enricher.dashboard:app", ...)
app = create_app()
