"""Browser-agent artifact schema — the stored ``company_scripts.script`` shape for
``transport='browser_agent'`` (E7 Stagehand pivot, ``script_version=2``).

A browser-agent artifact is NOT the multi-primitive HTTP ``steps`` recipe
(:mod:`api.services.recipe_schema`). It is the small, declarative description of a
bounded Stagehand session: an entry URL, an ``extract`` (instruction + JSON schema),
an OPTIONAL ``pagination`` (a next-page action + a hard page cap), the stable
``id_field`` (the crux — §3.4), an ``expected_min_jobs`` floor, and a completeness
``oracle`` that is ALWAYS ``self_consistent`` (a browser agent reads a rendered page
and can never prove a trusted total, so the board is shown but never closes until it
earns the 3-run VERIFIED streak the leaf task enforces).

Like :mod:`recipe_schema` this is pure data validation — it must NEVER import an
agent, an LLM client, or a browser driver (``stagehand``/``browserbase``). It is
validated on **write** (discovery, before storing) *and* on **read**
(``runner.run_browser_agent`` before every bounded session), because a stored script
is data that drifts. The ``max_pages ≤ 3`` bound is enforced at BOTH times (§4).
"""

from __future__ import annotations

from typing import Any

# The transport column value this schema governs, and the artifact's script_version.
BROWSER_AGENT_TRANSPORT = "browser_agent"
BROWSER_AGENT_SCRIPT_VERSION = 2

# HARD page cap for a bounded session — rejected at write AND read (§4). Discovery
# and nightly replay share it, so an Amazon-sized board can never blow up in either
# phase. NEVER raise this without re-reading §4 (belt, suspenders, and a hard stop).
MAX_PAGES_CAP = 3

# A browser-agent (rendered-page) board publishes no trustworthy total, so it is
# ALWAYS self_consistent — the safe oracle that shows the board but only closes a
# job after a 3-run VERIFIED streak. Any other oracle on a browser-agent artifact is
# a bug (it would claim a completeness proof the transport cannot deliver).
BROWSER_AGENT_ORACLE_KINDS = ("self_consistent",)

# The transport vocabulary v2 knows about: the HTTP replay transports PLUS the new
# browser-agent transport. Kept here (not in recipe_schema) so the HTTP validator's
# closed vocabulary stays HTTP-only.
TRANSPORTS_V2 = ("http_json", "http_html", BROWSER_AGENT_TRANSPORT)


class BrowserAgentScriptError(ValueError):
    """A browser-agent artifact is structurally invalid. Subclasses ``ValueError``
    so the leaf task's / discovery's narrow ``except`` records it as a FAILED /
    REFUSED outcome (never a silent no-op). The message names the offending field."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise BrowserAgentScriptError(msg)


def _require_str(obj: dict[str, Any], key: str, where: str) -> None:
    _require(
        isinstance(obj.get(key), str) and bool(obj[key]),
        f"{where}.{key} must be a non-empty string",
    )


def _require_https(obj: dict[str, Any], key: str, where: str) -> None:
    url = obj.get(key)
    _require(
        isinstance(url, str) and url.startswith("https://"),
        f"{where}.{key} must be an https:// string",
    )


def _reject_unknown_keys(obj: dict[str, Any], allowed: set[str], where: str) -> None:
    extra = set(obj) - allowed
    _require(not extra, f"{where}: unknown key(s) {sorted(extra)} — a typo must fail loudly")


def _validate_extract(extract: Any) -> None:
    _require(isinstance(extract, dict), "extract must be an object")
    assert isinstance(extract, dict)  # narrow for mypy
    _reject_unknown_keys(extract, {"instruction", "schema"}, "extract")
    _require_str(extract, "instruction", "extract")
    schema = extract.get("schema")
    _require(
        isinstance(schema, dict) and bool(schema),
        "extract.schema must be a non-empty JSON-schema object describing the job rows",
    )


def _validate_pagination(pagination: Any) -> None:
    _require(isinstance(pagination, dict), "pagination must be an object")
    assert isinstance(pagination, dict)  # narrow for mypy
    _reject_unknown_keys(pagination, {"next_action", "max_pages"}, "pagination")
    _require_str(pagination, "next_action", "pagination")
    max_pages = pagination.get("max_pages")
    _require(
        isinstance(max_pages, int) and not isinstance(max_pages, bool),
        "pagination.max_pages must be an int",
    )
    assert isinstance(max_pages, int)  # narrow for mypy; _require already raised otherwise
    _require(max_pages >= 1, "pagination.max_pages must be an int >= 1")
    # THE BOUND (§4): rejected if > 3 at write AND read time.
    _require(
        max_pages <= MAX_PAGES_CAP,
        f"pagination.max_pages={max_pages} exceeds the hard cap of {MAX_PAGES_CAP} — "
        "a bounded browser-agent session never crawls a whole board (§4)",
    )


def validate_browser_agent_script(
    script: dict[str, Any],
    *,
    transport: str | None = None,
    oracle_kind: str | None = None,
) -> dict[str, Any]:
    """Validate a browser-agent artifact, raising :class:`BrowserAgentScriptError`
    naming what is wrong. Runs on **write** and on **read**.

    When ``transport`` / ``oracle_kind`` (the ``company_scripts`` column values) are
    supplied, the artifact's own ``transport`` and ``oracle.kind`` are asserted equal
    to them — the JSONB must not drift from the columns that route it (mirroring
    :func:`recipe_schema.validate_recipe`).
    """
    _require(isinstance(script, dict), "script must be an object")

    _reject_unknown_keys(
        script,
        {
            "script_version", "transport", "entry_url", "extract", "pagination",
            "id_field", "expected_min_jobs", "oracle", "observed_actions",
            "discovered_at", "discovered_by",
        },
        "script",
    )

    _require(
        script.get("script_version") == BROWSER_AGENT_SCRIPT_VERSION,
        f"script_version must be {BROWSER_AGENT_SCRIPT_VERSION}, "
        f"got {script.get('script_version')!r}",
    )

    tr = script.get("transport")
    _require(
        tr == BROWSER_AGENT_TRANSPORT,
        f"transport must be {BROWSER_AGENT_TRANSPORT!r}, got {tr!r}",
    )
    if transport is not None:
        _require(
            tr == transport,
            f"script.transport {tr!r} != company_scripts.transport {transport!r}",
        )

    _require_https(script, "entry_url", "script")
    _validate_extract(script.get("extract"))

    # pagination is OPTIONAL (absent = single page).
    if "pagination" in script:
        _validate_pagination(script["pagination"])

    # id_field — the stable dedupe key. Its VALUES are proven stable by the runner
    # (§3.4); the schema only requires the field name be declared.
    _require_str(script, "id_field", "script")

    _require(
        isinstance(script.get("expected_min_jobs"), int)
        and not isinstance(script["expected_min_jobs"], bool)
        and script["expected_min_jobs"] > 0,
        "script.expected_min_jobs must be a positive int",
    )

    oracle = script.get("oracle")
    _require(isinstance(oracle, dict), "oracle must be an object")
    assert isinstance(oracle, dict)  # narrow for mypy
    _reject_unknown_keys(oracle, {"kind"}, "oracle")
    kind = oracle.get("kind")
    _require(
        kind in BROWSER_AGENT_ORACLE_KINDS,
        f"oracle.kind must be one of {BROWSER_AGENT_ORACLE_KINDS} for a browser-agent "
        f"board (a rendered page proves no trusted total), got {kind!r}",
    )
    if oracle_kind is not None:
        _require(
            kind == oracle_kind,
            f"script.oracle.kind {kind!r} != company_scripts.oracle_kind {oracle_kind!r}",
        )

    # observed_actions is an OPTIONAL cache seed for a future action-replay tier.
    if "observed_actions" in script:
        _require(
            isinstance(script["observed_actions"], list),
            "observed_actions must be a list when present",
        )

    return script


def effective_max_pages(script: dict[str, Any]) -> int:
    """The bounded page count for this artifact, clamped to the hard cap (§4).

    ``min(pagination.max_pages, MAX_PAGES_CAP)``; ``1`` when there is no pagination
    block (single page). Both discovery and replay drive the subprocess loop over
    this exact value, so neither phase can exceed the bound even if a stored script
    drifted past validation.
    """
    pagination = script.get("pagination")
    if not isinstance(pagination, dict):
        return 1
    declared = pagination.get("max_pages")
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        return 1
    return min(declared, MAX_PAGES_CAP)
