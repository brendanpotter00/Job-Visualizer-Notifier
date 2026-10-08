"""Free ATS board check against the public job-board APIs (from the POC's ``ats_check``).

The provider, token and URLs come from a Parallel Task output, so they are
untrusted: a token is only used when it is a plain slug, and only the three
fixed API hosts below are ever requested.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

ATS_URL_PATTERNS = {
    "greenhouse": r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)",
    "ashby": r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)",
    "lever": r"jobs\.lever\.co/([A-Za-z0-9_-]+)",
}
API_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{tok}/jobs",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{tok}",
    "lever": "https://api.lever.co/v0/postings/{tok}?mode=json",
}
PUBLIC_BOARD_URLS = {
    "greenhouse": "https://job-boards.greenhouse.io/{tok}",
    "ashby": "https://jobs.ashbyhq.com/{tok}",
    "lever": "https://jobs.lever.co/{tok}",
}
ATS_PROVIDERS = ("greenhouse", "ashby", "lever", "gem", "workday", "eightfold", "other", "none")

_TOKEN = re.compile(r"^[A-Za-z0-9_.%-]{1,100}$")


def safe_token(token: Any) -> str | None:
    if isinstance(token, str) and _TOKEN.match(token.strip()) and token.strip() not in (".", ".."):
        return token.strip()
    return None


def safe_http_url(value: Any) -> str | None:
    """An http(s) URL, or None. Keeps ``javascript:`` and friends off the admin page."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v or any(c.isspace() for c in v) or len(v) > 2000:
        return None
    if re.match(r"^https?://[^/?#\s]+", v, re.I):
        return v
    return None


def _candidates(provider: str | None, token: str | None, urls: list[str | None]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    tok = safe_token(token)
    if provider in API_URLS and tok:
        out.append((provider, tok))
    for prov, pat in ATS_URL_PATTERNS.items():
        for url in urls:
            m = re.search(pat, url or "")
            if m and safe_token(m.group(1)) and (prov, m.group(1)) not in out:
                out.append((prov, m.group(1)))
    return out


@dataclass(frozen=True)
class BoardProblem:
    """One candidate board that could not be checked. ``transient`` means the answer
    says nothing about the board (timeout, connection error, 429, 5xx)."""

    candidate: str  # "<provider>/<token>"
    detail: str
    transient: bool

    def note(self) -> str:
        return f"ATS check {self.candidate}: {self.detail}"


@dataclass
class BoardCheck:
    ats: dict[str, Any]
    problems: list[BoardProblem] = field(default_factory=list)

    @property
    def transient_failure(self) -> bool:
        """Nothing verified with jobs, and at least one candidate failed transiently, so
        "no board" is not a safe conclusion yet."""
        return not board_has_jobs(self.ats) and any(p.transient for p in self.problems)


def check_board(
    provider: str | None,
    token: str | None,
    careers_url: str | None,
    board_url: str | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout_s: float = 20.0,
) -> BoardCheck:
    """Verify the board and report every candidate that could not be checked.

    ``verified`` means the public API answered 200 with a job list. The first
    candidate with at least one job wins; otherwise the first one that answered
    with an empty list.
    """
    prov = provider if provider in ATS_PROVIDERS else ("other" if provider else "none")
    brief_board_url = safe_http_url(board_url)
    result: dict[str, Any] = {
        "provider": prov,
        "board_token": safe_token(token),
        "board_url": brief_board_url,
        "verified": False,
        "job_count": None,
        "checked_url": None,
    }
    problems: list[BoardProblem] = []
    candidates = _candidates(provider, token, [careers_url, brief_board_url])
    if not candidates:
        return BoardCheck(result, problems)
    empty_hit: dict[str, Any] | None = None
    with httpx.Client(timeout=timeout_s, follow_redirects=True, transport=transport) as h:
        for cprov, tok in candidates:
            label = f"{cprov}/{tok}"
            url = API_URLS[cprov].format(tok=quote(tok, safe="%"))
            try:
                r = h.get(url)
            except httpx.HTTPError as e:
                problems.append(BoardProblem(label, type(e).__name__, transient=True))
                continue
            if r.status_code != 200:
                problems.append(BoardProblem(label, f"HTTP {r.status_code}",
                                             transient=r.status_code == 429 or r.status_code >= 500))
                continue
            if not r.headers.get("content-type", "").startswith("application/json"):
                problems.append(BoardProblem(label, "answered 200 without JSON", transient=False))
                continue
            try:
                data = r.json()
            except json.JSONDecodeError:
                problems.append(BoardProblem(label, "invalid JSON", transient=False))
                continue
            jobs = data.get("jobs") if isinstance(data, dict) else data
            if not isinstance(jobs, list):
                problems.append(BoardProblem(label, "no job list in the response", transient=False))
                continue
            hit = {
                "provider": cprov,
                "board_token": tok,
                "board_url": brief_board_url or PUBLIC_BOARD_URLS[cprov].format(tok=tok),
                "verified": True,
                "job_count": len(jobs),
                "checked_url": url,
            }
            if jobs:
                result.update(hit)
                return BoardCheck(result, problems)
            if empty_hit is None:
                empty_hit = hit
    if empty_hit is not None:
        result.update(empty_hit)
    return BoardCheck(result, problems)


def board_has_jobs(ats: dict[str, Any]) -> bool:
    """A board on one of the checked providers answered with at least one job."""
    return bool(ats["verified"] and ats["provider"] in API_URLS and (ats["job_count"] or 0) >= 1)
