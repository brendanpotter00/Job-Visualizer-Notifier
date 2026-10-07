"""HTTP client for the backend's internal Launch Radar routes (CONTRACT §2.3).

The loop calls the backend directly (never through Vercel) and authenticates
with ``X-Internal-Key``. The key is sent as a header and never logged; errors
carry the method, path, status and the backend's ``detail`` only.

Only GETs are retried (twice, on connection errors). A POST/PUT/PATCH is never
retried: a reservation or a card insert must not be applied twice.
"""

from __future__ import annotations

from typing import Any, Iterable

import httpx

PREFIX = "/api/internal/launch-radar"
SEEN_CHUNK = 100
GET_RETRIES = 2


class BackendError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, detail: Any) -> None:
        super().__init__(f"{method} {path} -> {status}: {detail}")
        self.method = method
        self.path = path
        self.status = status
        self.detail = detail


class BudgetExceeded(RuntimeError):
    """402 from ``/reserve``: the run budget or the global cap would be passed."""

    def __init__(self, reason: str, run_spend: float, total_spend: float, cap: float) -> None:
        super().__init__(
            f"budget refused ({reason}): run ${run_spend:.3f}, total ${total_spend:.3f} of ${cap:.2f}"
        )
        self.reason = reason
        self.run_spend = run_spend
        self.total_spend = total_spend
        self.cap = cap


class DomainSeen(RuntimeError):
    """409 ``domain already posted`` from ``POST /cards``."""


def _detail(resp: httpx.Response) -> Any:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    return body.get("detail", body) if isinstance(body, dict) else body


class BackendClient:
    def __init__(
        self,
        base_url: str,
        internal_api_key: str | None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        headers = {"X-Internal-Key": internal_api_key} if internal_api_key else {}
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "BackendClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- plumbing -------------------------------------------------------------
    def _send(self, method: str, path: str, *, json: Any = None, params: Any = None) -> httpx.Response:
        url = PREFIX + path
        attempts = 1 + (GET_RETRIES if method == "GET" else 0)
        for attempt in range(attempts):
            try:
                return self._http.request(method, url, json=json, params=params)
            except httpx.TransportError:
                if attempt == attempts - 1:
                    raise
        raise AssertionError("unreachable")

    def _json(self, method: str, path: str, ok: tuple[int, ...], **kw: Any) -> Any:
        resp = self._send(method, path, **kw)
        if resp.status_code not in ok:
            raise BackendError(method, path, resp.status_code, _detail(resp))
        return resp.json()

    # ---- runs and the ledger ----------------------------------------------------
    def start_run(self, run_uuid: str, host: str | None, budget_usd: float) -> dict[str, Any]:
        body = {"run_uuid": run_uuid, "host": host[:64] if host else None, "budget_usd": budget_usd}
        return self._json("POST", "/runs", (201,), json=body)

    def reserve(
        self, run_uuid: str, step: str, est_usd: float, *, domain: str | None = None, accrued: bool = False
    ) -> dict[str, Any]:
        path = f"/runs/{run_uuid}/reserve"
        body = {"step": step, "est_usd": est_usd, "domain": domain, "accrued": accrued}
        resp = self._send("POST", path, json=body)
        if resp.status_code == 402:
            d = _detail(resp)
            if not isinstance(d, dict):
                raise BackendError("POST", path, 402, d)
            raise BudgetExceeded(
                str(d.get("reason")), float(d.get("run_spend_usd", 0)), float(d.get("total_spend_usd", 0)),
                float(d.get("cap_usd", 0)),
            )
        if resp.status_code != 200:
            raise BackendError("POST", path, resp.status_code, _detail(resp))
        return resp.json()

    def finish_run(
        self, run_uuid: str, status: str, events_read: int, cards_posted: int, notes: str | None
    ) -> dict[str, Any]:
        body = {"status": status, "events_read": events_read, "cards_posted": cards_posted,
                "notes": notes[:500] if notes else None}
        return self._json("POST", f"/runs/{run_uuid}/finish", (200,), json=body)

    # ---- monitors -----------------------------------------------------------------
    def list_monitors(self) -> list[dict[str, Any]]:
        return list(self._json("GET", "/monitors", (200,))["monitors"])

    def put_monitor(self, slot: str, row: dict[str, Any]) -> dict[str, Any]:
        return self._json("PUT", f"/monitors/{slot}", (200,), json=row)

    def patch_monitor(self, slot: str, **fields: Any) -> dict[str, Any]:
        if not fields:
            raise ValueError("patch_monitor needs at least one field")
        return self._json("PATCH", f"/monitors/{slot}", (200,), json=fields)

    # ---- dedupe and cards -----------------------------------------------------------
    def seen(self, domains: Iterable[str], names: Iterable[str]) -> dict[str, dict[str, Any]]:
        """``GET /seen`` in chunks of 100; merged ``{"domains": {...}, "names": {...}}``."""
        doms, nms = list(dict.fromkeys(domains)), list(dict.fromkeys(names))
        out: dict[str, dict[str, Any]] = {"domains": {}, "names": {}}
        for i in range(0, max(len(doms), len(nms)), SEEN_CHUNK):
            params = [("domain", d) for d in doms[i:i + SEEN_CHUNK]] + [("name", n) for n in nms[i:i + SEEN_CHUNK]]
            got = self._json("GET", "/seen", (200,), params=params)
            out["domains"].update(got.get("domains") or {})
            out["names"].update(got.get("names") or {})
        return out

    def post_card(self, run_uuid: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self._send("POST", "/cards", json={"run_uuid": run_uuid, "payload": payload})
        if resp.status_code == 409 and _detail(resp) == "domain already posted":
            raise DomainSeen(payload.get("domain"))
        if resp.status_code != 201:
            raise BackendError("POST", "/cards", resp.status_code, _detail(resp))
        return resp.json()

    def set_pr(self, card_id: int, pr_url: str) -> dict[str, Any]:
        return self._json("PATCH", f"/cards/{card_id}/pr", (200,), json={"pr_url": pr_url})

    def pr_candidates(self, limit: int = 1) -> list[dict[str, Any]]:
        return list(self._json("GET", "/pr-candidates", (200,), params={"limit": limit})["cards"])
