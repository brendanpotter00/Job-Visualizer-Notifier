"""HMAC verification for the OPTIONAL inbound edge (server.py).

In the pull model the laptop only makes outbound calls, so this is not on the
critical path. It exists so a future push/inbound webhook is authenticated the
same way boop verifies Composio: HMAC-SHA256 over "{id}.{timestamp}.{body}",
base64-encoded, header format `v1,<b64>`, with a 5-minute freshness window.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

FRESHNESS_WINDOW_SECONDS = 5 * 60

HDR_ID = "webhook-id"
HDR_TIMESTAMP = "webhook-timestamp"
HDR_SIGNATURE = "webhook-signature"


def sign(secret: str, webhook_id: str, timestamp: str, raw_body: bytes) -> str:
    """Produce the `v1,<base64>` signature header value for a payload."""
    message = f"{webhook_id}.{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode("ascii")


def _parse_v1(signature_header: str) -> list[str]:
    out: list[str] = []
    for token in signature_header.split(" "):
        version, _, value = token.partition(",")
        if version == "v1" and value:
            out.append(value)
    return out


def is_fresh(timestamp: str, now: float | None = None) -> bool:
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return False
    ts_seconds = ts / 1000.0 if ts > 1e12 else ts
    now_seconds = now if now is not None else time.time()
    return abs(now_seconds - ts_seconds) <= FRESHNESS_WINDOW_SECONDS


def verify(
    secret: str, webhook_id: str, timestamp: str, signature_header: str,
    raw_body: bytes, now: float | None = None,
) -> bool:
    if not (secret and webhook_id and timestamp and signature_header and raw_body):
        return False
    if not is_fresh(timestamp, now=now):
        return False
    expected = sign(secret, webhook_id, timestamp, raw_body).split(",", 1)[1]
    for provided in _parse_v1(signature_header):
        if hmac.compare_digest(provided, expected):
            return True
    return False
