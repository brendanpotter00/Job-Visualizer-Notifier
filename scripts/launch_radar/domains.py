"""Domain normalization (CONTRACT §3) and the big-tech filter.

The backend carries an identical copy of ``normalize_domain``
(``src/backend/api/services/launch_radar.py``); both test suites pin the same
vectors, so a card's ``domain`` always matches the backend's UNIQUE key.
"""

from __future__ import annotations

import re

_NULLISH = {"", "na", "n/a", "none", "null", "unknown"}

# A normalized domain is also used as a local state file name, so anything the
# web hands us that is not a plain hostname is rejected before it gets that far.
_HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")

BIG_TECH = {
    "google.com", "alphabet.com", "apple.com", "microsoft.com", "amazon.com", "aws.amazon.com", "meta.com",
    "facebook.com", "nvidia.com", "openai.com", "anthropic.com", "x.ai", "tesla.com", "ibm.com", "oracle.com",
    "salesforce.com", "intel.com", "amd.com", "netflix.com", "tiktok.com", "bytedance.com", "samsung.com",
    "adobe.com", "uber.com", "deepmind.google", "mistral.ai", "databricks.com",
}


def normalize_domain(value: object) -> str | None:
    """Ported verbatim from POC ``poc.py:155``."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in _NULLISH:
        return None
    v = re.sub(r"^[a-z][a-z0-9+.-]*://", "", v)
    v = v.split("/")[0].split("?")[0].split("#")[0]
    v = v.split("@")[-1].split(":")[0]
    if v.startswith("www."):
        v = v[4:]
    v = v.rstrip(".")
    return v if "." in v else None


def is_hostname(domain: str) -> bool:
    """True for a plain DNS name (safe as a file name and a URL host)."""
    return bool(_HOSTNAME.match(domain)) and len(domain) <= 253


def is_big_tech(domain: str) -> bool:
    return domain in BIG_TECH or any(domain.endswith("." + b) for b in BIG_TECH)
