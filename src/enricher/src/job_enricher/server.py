"""OPTIONAL inbound edge (FastAPI).

Not on the pull-model critical path — the laptop normally only makes OUTBOUND
calls to JVN. This exists so a future push/inbound path is authenticated exactly
like boop: HMAC over the raw body, verified BEFORE JSON parse. It never runs
Claude; it only enqueues into the local inbox. Disabled unless EDGE_ENABLED=1.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, Response

from job_enricher import security
from job_enricher.config import settings
from job_enricher.store import Store

app = FastAPI(title="job-enricher edge")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/enrich")
async def enrich(request: Request) -> Response:
    raw = await request.body()  # exact bytes BEFORE json parse (HMAC integrity)
    if not settings.edge_hmac_secret:
        return Response(status_code=503)
    ok = security.verify(
        settings.edge_hmac_secret,
        request.headers.get(security.HDR_ID, ""),
        request.headers.get(security.HDR_TIMESTAMP, ""),
        request.headers.get(security.HDR_SIGNATURE, ""),
        raw,
    )
    if not ok:
        return Response(status_code=401)

    import json as _json

    payload = _json.loads(raw)
    jobs = payload.get("jobs", [])
    from job_enricher.jvn_client import JVNClient

    rows = [JVNClient._to_inbox_row(j) for j in jobs]
    store = Store()
    store.init_schema()
    inserted, _ = store.enqueue_inbox(rows)
    return Response(
        content=_json.dumps({"accepted": inserted}),
        media_type="application/json",
        status_code=202,
    )
