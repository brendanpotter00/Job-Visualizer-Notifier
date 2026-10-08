"""``radar.py rescore``: recompute the scores of existing cards from what they store. Free.

No Parallel client is created, no backend run is opened and nothing is reserved: a
rescore is pure computation on stored payloads (``scoring.rescored_scores``). Per card:

- the leaders' part of Talent is carried (``talent_leaders``, or a legacy card's raw
  ``talent`` rescaled to 0-50), with its reasons: the card does not keep the pedigree
  confidence the leader rubric weighs by, and a rescore never changes leader inputs;
- the team's part is scored from the stored ``team_stats`` tally, then the two are blended;
- the VC score is recomputed from the stored ``funding`` block.

A card is PUT (``PUT /cards/{id}/payload``; status and posted_at stay) only when its
``scores`` changed, so a second run is a no-op. The event date is normalized on the way
(as ``refresh`` does) so an old card is never rejected for it. Every live status is
selected (new, saved, archived): it costs nothing. A card deleted meanwhile (404) is
counted, not fatal; any other backend error is counted and the command exits 1 after
the summary. ``--dry-run`` prints the same lines and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .backend_client import BackendError, CardGone
from .card import announced_on
from .pipeline import EXIT_ERROR, EXIT_OK, Deps
from .scoring import rescored_scores

LIVE_STATUSES = ("new", "saved", "archived")


@dataclass
class RescoreOptions:
    domains: frozenset[str] = frozenset()
    all_cards: bool = False
    dry_run: bool = False


def _num(v: Any) -> str:
    return "-" if v is None else str(v)


def _talent_detail(scores: dict[str, Any]) -> str:
    basis = scores.get("talent_basis")
    if basis == "both":
        return f" (leaders {scores['talent_leaders']} + team {scores['talent_team']})"
    if basis == "leaders":
        return f" (leaders {scores['talent_leaders']}, doubled: no team data)"
    if basis == "team":
        return f" (team {scores['talent_team']}, doubled: no leader data)"
    return ""


def describe(company: str, old: dict[str, Any], new: dict[str, Any]) -> str:
    """``Lightfield: talent 70→67 (leaders 37 + team 30), vc 100→100``."""
    return (f"{company}: talent {_num(old.get('talent'))}→{_num(new.get('talent'))}{_talent_detail(new)}, "
            f"vc {_num(old.get('vc'))}→{_num(new.get('vc'))}")


def rescored_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """``payload`` with its scores recomputed and its event date normalized; nothing else changes."""
    new = {**payload, "scores": rescored_scores(payload)}
    if isinstance(payload.get("event"), dict):
        new["event"] = {**payload["event"], "announced_at": announced_on(payload["event"].get("announced_at"))}
    return new


def rescore(opts: RescoreOptions, deps: Deps) -> int:
    log = deps.log
    if opts.all_cards == bool(opts.domains):
        log("rescore: give exactly one of --domains or --all")
        return EXIT_ERROR
    cards = (deps.backend.cards(all_cards=True, statuses=LIVE_STATUSES) if opts.all_cards
             else deps.backend.cards(domains=sorted(opts.domains), statuses=LIVE_STATUSES))
    for dom in sorted(opts.domains - {c.get("domain") for c in cards}):
        log(f"skip {dom}: no live card")
    changed = unchanged = gone = errors = 0
    verb = "would update" if opts.dry_run else "updated"
    for card in cards:
        card_id, payload = card.get("id"), card.get("payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("scores"), dict):
            errors += 1
            log(f"error     card {card_id} ({card.get('domain')}): no stored payload scores")
            continue
        new = rescored_payload(payload)
        line = describe(str(payload.get("company") or card.get("domain")), payload["scores"], new["scores"])
        if new["scores"] == payload["scores"]:
            unchanged += 1
            log(f"unchanged card {card_id} {line}")
            continue
        if opts.dry_run:
            changed += 1
            log(f"{verb} card {card_id} {line}")
            continue
        try:
            deps.backend.put_payload(int(card_id), new)
        except CardGone:
            gone += 1
            log(f"gone      card {card_id} {line}: deleted meanwhile")
            continue
        except (BackendError, httpx.HTTPError) as e:
            # Counted and reported in the exit code; the PUT is idempotent, so re-running is safe.
            errors += 1
            log(f"error     card {card_id} {line}: {type(e).__name__}: {e}")
            continue
        changed += 1
        log(f"{verb} card {card_id} {line}")
    head = "rescore (dry run, nothing written): would change" if opts.dry_run else "rescore: changed"
    log(f"{head} {changed}, unchanged {unchanged}, gone {gone}, errors {errors}")
    return EXIT_ERROR if errors else EXIT_OK


__all__ = ["RescoreOptions", "describe", "rescore", "rescored_payload"]
