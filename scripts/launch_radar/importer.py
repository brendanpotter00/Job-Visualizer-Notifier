"""``radar.py import``: post cards exported by ``export_cards.py`` to the backend.

Moves cards researched on one machine to another backend (in practice: this laptop's
local database to production) WITHOUT re-running any research. Each card's stored
payload goes through the same ``POST /cards`` the loop uses, under one backend run
opened and finished for the import (``host`` = this machine). No Parallel client is
created and nothing is reserved: the research was paid for where it ran, and each
payload's ``cost_usd`` records what it cost.

The file is untrusted data. It is parsed as JSON only, never executed, and the whole
file is validated before the first POST: the format tag, a live status, and a payload
object whose ``domain`` is the card's normalized ``domain``. The backend re-validates
every payload against ``LaunchRadarPayload``.

- A 409 ``domain already posted`` is a skip, so re-running after a failure is safe.
- Any other error stops the import (exit 1) after reporting what was imported so far.
- The internal API only creates ``new`` cards, so a card that was saved or archived on
  the exporting machine arrives as ``new``; the summary lists them so the admin can
  re-save or re-archive them on ``/admin/launch-radar``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .backend_client import BackendError, DomainSeen
from .domains import is_hostname, normalize_domain
from .pipeline import EXIT_ERROR, EXIT_OK, Deps, RunCounters, admin_run

FORMAT = "launch-radar-cards/v1"  # export_cards.FORMAT writes exactly this
LIVE_STATUSES = ("new", "saved", "archived")
# POST /runs needs a budget > 0; an import reserves nothing against it.
IMPORT_RUN_BUDGET_USD = 0.01
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_CARDS = 5000


class ImportFileError(ValueError):
    """The file is not a valid ``launch-radar-cards/v1`` export. Nothing was posted."""


@dataclass(frozen=True)
class ExportedCard:
    domain: str
    status: str
    company: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ExportFile:
    source: str
    exported_at: str
    cards: list[ExportedCard]


def _printable(value: Any, limit: int) -> str:
    """Untrusted text for a log line: printable characters only (no terminal escapes), clipped."""
    return "".join(ch for ch in str(value) if ch.isprintable())[:limit]


def parse_export(doc: Any) -> ExportFile:
    """Validate a decoded export document. Raises ``ImportFileError`` naming the first problem."""
    if not isinstance(doc, dict):
        raise ImportFileError("the file is not a JSON object")
    if doc.get("format") != FORMAT:
        raise ImportFileError(f"format must be {FORMAT!r}, got {_printable(doc.get('format'), 60)!r}")
    raw = doc.get("cards")
    if not isinstance(raw, list):
        raise ImportFileError("'cards' must be a list")
    if len(raw) > MAX_CARDS:
        raise ImportFileError(f"{len(raw)} cards is more than the {MAX_CARDS} an import accepts")
    cards: list[ExportedCard] = []
    seen: set[str] = set()
    for i, c in enumerate(raw):
        where = f"card {i}"
        if not isinstance(c, dict):
            raise ImportFileError(f"{where}: not an object")
        dom = c.get("domain")
        if not isinstance(dom, str) or normalize_domain(dom) != dom or not is_hostname(dom):
            raise ImportFileError(f"{where}: domain {_printable(dom, 80)!r} is not a normalized domain")
        where = f"card {i} ({dom})"
        if dom in seen:
            raise ImportFileError(f"{where}: duplicate domain")
        seen.add(dom)
        if c.get("status") not in LIVE_STATUSES:
            raise ImportFileError(f"{where}: status must be one of {', '.join(LIVE_STATUSES)}")
        posted = c.get("posted_at")
        if posted is not None and not isinstance(posted, str):
            raise ImportFileError(f"{where}: posted_at must be a string or null")
        payload = c.get("payload")
        if not isinstance(payload, dict):
            raise ImportFileError(f"{where}: payload must be an object")
        if payload.get("domain") != dom:
            raise ImportFileError(f"{where}: payload domain {_printable(payload.get('domain'), 80)!r} "
                                  f"does not match the card's domain")
        company = payload.get("company")
        if not isinstance(company, str) or not company.strip():
            raise ImportFileError(f"{where}: payload company must be a non-empty string")
        cards.append(ExportedCard(domain=dom, status=c["status"], company=_printable(company, 80), payload=payload))
    return ExportFile(source=_printable(doc.get("source") or "unknown", 64),
                      exported_at=_printable(doc.get("exported_at") or "unknown", 40), cards=cards)


def load_export(path: Path) -> ExportFile:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ImportFileError(f"{path} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ImportFileError(f"cannot read {path}: {e.strerror or type(e).__name__}") from e
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ImportFileError(f"{path} is not valid UTF-8 JSON: {e}") from e
    return parse_export(doc)


@dataclass
class Tally:
    imported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: str | None = None  # the card whose POST raised
    posted_all: bool = False  # every card was attempted (a later error is the run's finish)


def _status_note(cards: list[ExportedCard], on_backend: set[str], deps: Deps) -> None:
    moved = [c for c in cards if c.status != "new" and c.domain in on_backend]
    if not moved:
        return
    deps.log(f"note: {len(moved)} card(s) were saved or archived on the exporting machine. The internal API "
             "creates every card as new, so re-apply these on /admin/launch-radar (if not done already):")
    for c in moved:
        deps.log(f"  {c.status:<8} {c.domain} ({c.company})")


def _dry_run(export: ExportFile, deps: Deps) -> int:
    """Read-only: ``GET /seen`` says which domains the backend already has. No run, no POST."""
    doms = [c.domain for c in export.cards]
    have = set(deps.backend.seen(doms, [])["domains"]) & set(doms) if doms else set()
    for c in export.cards:
        deps.log(f"{'would skip' if c.domain in have else 'would import'} {c.domain} ({c.company})"
                 + (f" [{c.status}]" if c.status != "new" else ""))
    _status_note(export.cards, set(doms), deps)
    deps.log(f"import dry run: {len(export.cards)} card(s) from {export.source} ({export.exported_at}): "
             f"would import {len(doms) - len(have)}, would skip {len(have)} already on the backend; "
             "nothing posted")
    return EXIT_OK


def import_cards(export: ExportFile, deps: Deps, *, dry_run: bool = False) -> int:
    """Post every card in ``export`` (see the module docstring). Exit 0 done, 1 stopped on an error."""
    if dry_run:
        return _dry_run(export, deps)
    tally = Tally()
    counters = RunCounters()

    def body(run_uuid: str) -> str:
        for c in export.cards:
            try:
                posted = deps.backend.post_card(run_uuid, c.payload)
            except DomainSeen:
                tally.skipped.append(c.domain)
                deps.log(f"skipped  {c.domain}: already on the backend (409)")
                continue
            except BaseException:
                tally.failed = c.domain
                raise
            tally.imported.append(c.domain)
            counters.cards_posted += 1
            deps.log(f"imported {c.domain} ({c.company}) as card {posted.get('id')}"
                     + (" · already tracked" if posted.get("tracked_company_id") else ""))
        tally.posted_all = True
        return (f"imported {len(tally.imported)}, skipped {len(tally.skipped)} as duplicate, from "
                f"{export.source} ({export.exported_at})")

    code = EXIT_ERROR
    try:
        code = admin_run(deps, "import", body, budget=IMPORT_RUN_BUDGET_USD, counters=counters)
    except (BackendError, httpx.HTTPError) as e:
        where = (f"at {tally.failed}" if tally.failed else
                 "after every card (closing the backend run failed)" if tally.posted_all else
                 "before posting any card")
        deps.log(f"import: stopped {where}: {type(e).__name__}: {e}")
        if isinstance(e, httpx.HTTPError) and tally.failed:
            deps.log(f"import: the POST for {tally.failed} may still have been stored; re-running is safe "
                     "(a card already on the backend is skipped with a 409)")
    finally:
        attempted = len(tally.imported) + len(tally.skipped) + (1 if tally.failed else 0)
        _status_note(export.cards, set(tally.imported) | set(tally.skipped), deps)
        deps.log(f"import summary: imported {len(tally.imported)} · skipped as duplicate {len(tally.skipped)} · "
                 f"failed {1 if tally.failed else 0}"
                 + (f" ({tally.failed})" if tally.failed else "")
                 + (f" · not attempted {len(export.cards) - attempted}" if attempted < len(export.cards) else "")
                 + f" · of {len(export.cards)} in the file")
    return code
