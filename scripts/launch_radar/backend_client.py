"""HTTP client for the backend's internal Launch Radar routes (CONTRACT §2.3).

The loop calls the backend directly (never through Vercel) and authenticates
with ``X-Internal-Key``. The key is sent as a header and never logged; errors
carry the method, path, status and the backend's ``detail`` only.

The add-company PR queue (saved-pr/PLAN.md §3.3) is ``pr_next``, ``pr_get``,
``pr_result``, ``pr_requeue`` and ``pr_requests``.

Only GETs are retried (twice, on connection errors). A POST/PUT/PATCH is never
retried: a reservation or a card insert must not be applied twice.
"""

from __future__ import annotations

from typing import Any, Iterable

import httpx

PREFIX = "/api/internal/launch-radar"
SEEN_CHUNK = 100
CARDS_LIMIT = 500  # the backend's maximum for GET /cards
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


class CardGone(RuntimeError):
    """404 from ``PUT /cards/{id}/payload``: the card is missing or was deleted."""


class PrRequestNotFound(RuntimeError):
    """404 from a ``/pr-requests/{card_id}`` route: no request, or the card was deleted."""


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

    def cards(
        self, *, domains: Iterable[str] = (), missing_talent: bool = False, all_cards: bool = False,
        statuses: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        """``GET /cards``: live cards with their stored payload, by domain (chunks of 100)
        and/or every card with no leaders' part of Talent (``missing_talent``), or every live
        card (``all_cards``, the explicit ``all=true`` opt-in), limited to ``statuses`` (empty:
        every live status). Exactly one of ``all_cards`` / (``domains`` and/or
        ``missing_talent``) is needed. Every match is returned: each query is paged by id
        (``after_id``) until a page comes back short, so no cap hides a card."""
        doms = list(dict.fromkeys(domains))
        if all_cards and (doms or missing_talent):
            raise ValueError("cards(all_cards=True) takes no domains or missing_talent")
        if not doms and not missing_talent and not all_cards:
            raise ValueError("cards() needs domains, missing_talent or all_cards")
        base = [("missing_talent", "true")] if missing_talent else []
        base += [("all", "true")] if all_cards else []
        base += [("status", s) for s in dict.fromkeys(statuses)]
        chunks = [[("domain", d) for d in doms[i:i + SEEN_CHUNK]] for i in range(0, len(doms), SEEN_CHUNK)] or [[]]
        out: dict[int, dict[str, Any]] = {}
        for chunk in chunks:
            after_id = 0
            while True:
                params = chunk + base + [("limit", CARDS_LIMIT), ("after_id", after_id)]
                page = self._json("GET", "/cards", (200,), params=params)["cards"]
                for card in page:
                    out[int(card["id"])] = card
                if len(page) < CARDS_LIMIT:
                    break
                after_id = max(int(card["id"]) for card in page)
        return [out[k] for k in sorted(out)]

    def put_payload(self, card_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """``PUT /cards/{id}/payload``: replace a live card's payload (status and posted_at stay)."""
        path = f"/cards/{card_id}/payload"
        resp = self._send("PUT", path, json={"payload": payload})
        if resp.status_code == 404:
            raise CardGone(f"card {card_id}")
        if resp.status_code != 200:
            raise BackendError("PUT", path, resp.status_code, _detail(resp))
        return resp.json()

    # ---- add-company PR requests (saved-pr/PLAN.md §3.3) ----------------------------------
    def pr_next(self) -> dict[str, Any] | None:
        """``POST /pr-requests/next``: the claimed card (now ``in_progress``), or None on
        204 (nothing claimable). Never retried: a lost response leaves an ``in_progress``
        claim that the backend recovers after 2 h."""
        resp = self._send("POST", "/pr-requests/next", json={})
        if resp.status_code == 204:
            return None
        if resp.status_code != 200:
            raise BackendError("POST", "/pr-requests/next", resp.status_code, _detail(resp))
        return resp.json()

    def _pr_call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        resp = self._send(method, path, **kw)
        if resp.status_code == 404:
            raise PrRequestNotFound(f"{method} {path}: {_detail(resp)}")
        if resp.status_code != 200:
            raise BackendError(method, path, resp.status_code, _detail(resp))
        return resp.json()

    def pr_get(self, card_id: int) -> dict[str, Any]:
        """``GET /pr-requests/{card_id}``: the request plus ``card_status``."""
        return self._pr_call("GET", f"/pr-requests/{int(card_id)}")

    def pr_result(
        self, card_id: int, outcome: str, *, pr_url: str | None = None, reason: str | None = None
    ) -> dict[str, Any]:
        """``POST /pr-requests/{card_id}/result``. 404 -> PrRequestNotFound; 409/422 -> BackendError."""
        body = {"outcome": outcome, "pr_url": pr_url, "reason": reason}
        return self._pr_call("POST", f"/pr-requests/{int(card_id)}/result", json=body)

    def pr_requeue(self, card_id: int) -> dict[str, Any]:
        """``POST /pr-requests/{card_id}/requeue`` (interactive ``pr-requeue`` only)."""
        return self._pr_call("POST", f"/pr-requests/{int(card_id)}/requeue", json={})

    def pr_requests(self, *, statuses: Iterable[str] = (), limit: int = 100) -> list[dict[str, Any]]:
        """``GET /pr-requests``: requests in ``statuses`` (empty: every status), oldest
        ``requested_at`` first, with ``domain`` and ``company``."""
        params = [("status", s) for s in dict.fromkeys(statuses)] + [("limit", limit)]
        return list(self._json("GET", "/pr-requests", (200,), params=params)["requests"])
