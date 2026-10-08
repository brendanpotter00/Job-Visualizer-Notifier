"""``radar.py grade-export`` / ``grade-apply``: the AI Talent grade (CONTRACT §6.6.1). Free.

The grade itself is written by Claude, not by this module: the ``launch-radar-grade``
skill spawns one subagent per card, which reads the card's input file and the rubric
(``.claude/skills/launch-radar-grade/rubric.md``) and returns one JSON object. This
module only moves data in and out, so nothing the model writes is ever run, and every
grade is validated before it reaches the backend:

- ``grade-export`` writes ``<dir>/inputs/<card_id>.json``: only what the rubric reads
  (what the company does, its leaders' histories, the team tally). No URLs, no team
  member names. It clears ``<dir>`` first, so a stale grade can never be applied to a
  card it was not written for.
- ``grade-apply`` reads ``<dir>/grades/<card_id>.json`` (what each subagent returned),
  validates it, re-reads the card, merges the grade into its ``scores`` and PUTs the
  payload (``PUT /cards/{id}/payload``; status and posted_at stay). It also writes
  ``<dir>/results.json``, one row per card, for a backtest table. ``--dry-run`` reads and
  validates everything and writes nothing to the backend.

With a grade, ``scores.talent`` IS the grade (``talent_ai.score``); the deterministic
blend moves to ``talent_rules`` with its parts and reasons unchanged, and stays the
fallback: a card the grader skipped or failed keeps its rule-based Talent.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .backend_client import BackendError, CardGone
from .pipeline import EXIT_ERROR, EXIT_OK, Deps
from .scoring import with_ai_grade

# Bump with the rubric's heading (rubric.md "— `v1`"): every card graded under an older
# version counts as ungraded again, so the nightly run re-grades it.
RUBRIC_VERSION = "v1"
PART_MAX = {"leaders": 40, "industry": 25, "team": 25, "track_record": 10}
CONFIDENCES = ("high", "medium", "low")
MAX_REASONS = 6
MAX_REASON_CHARS = 300
MAX_INDUSTRY_CHARS = 80
GRADED_STATUSES = ("new", "saved")
LIVE_STATUSES = ("new", "saved", "archived")

# The leader fields the rubric reads (no URLs, no free-form summary of where they are now).
_LEADER_FIELDS = ("name", "title", "schools", "prior_companies", "founded_before", "years_experience",
                  "industry_experience", "signals", "summary")
_TEAM_FIELDS = ("profiles_found", "team_size_estimate", "schools", "prior_employers")


class GradeError(ValueError):
    """A grade file that does not match the rubric's output contract."""


@dataclass
class ExportOptions:
    dir: Path
    domains: frozenset[str] = frozenset()
    all_cards: bool = False
    ungraded: bool = False
    include_archived: bool = False


def is_graded(scores: Any) -> bool:
    ai = scores.get("talent_ai") if isinstance(scores, dict) else None
    return isinstance(ai, dict) and ai.get("rubric_version") == RUBRIC_VERSION


def has_people_data(payload: dict[str, Any]) -> bool:
    team = payload.get("team_stats") if isinstance(payload.get("team_stats"), dict) else {}
    return bool(payload.get("leaders")) or bool(team.get("profiles_found"))


def grading_input(card_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """What one grader sees: the company, its leaders' histories and the team tally."""
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    funding = payload.get("funding") if isinstance(payload.get("funding"), dict) else {}
    latest = funding.get("latest_round") if isinstance(funding.get("latest_round"), dict) else {}
    team = payload.get("team_stats") if isinstance(payload.get("team_stats"), dict) else None
    leaders = [{k: lead.get(k) for k in _LEADER_FIELDS if lead.get(k) not in (None, [], "")}
               for lead in payload.get("leaders") or [] if isinstance(lead, dict)]
    return {
        "card_id": card_id,
        "rubric_version": RUBRIC_VERSION,
        "company": payload.get("company"),
        "domain": payload.get("domain"),
        "what_they_do": payload.get("what_they_do") or payload.get("one_liner"),
        "stage": latest.get("stage") or event.get("round"),
        "leaders": leaders,
        "team_stats": None if team is None else {k: team.get(k) for k in _TEAM_FIELDS},
    }


def export(opts: ExportOptions, deps: Deps) -> int:
    log = deps.log
    if sum([opts.all_cards, opts.ungraded, bool(opts.domains)]) != 1:
        log("grade-export: give exactly one of --domains, --all or --ungraded")
        return EXIT_ERROR
    statuses = LIVE_STATUSES if (opts.all_cards or opts.include_archived) else GRADED_STATUSES
    if opts.domains:
        cards = deps.backend.cards(domains=sorted(opts.domains), statuses=statuses)
    else:
        cards = deps.backend.cards(all_cards=True, statuses=statuses)
    if opts.dir.exists():
        shutil.rmtree(opts.dir)
    (opts.dir / "inputs").mkdir(parents=True)
    (opts.dir / "grades").mkdir()
    written = skipped = 0
    for card in sorted(cards, key=lambda c: int(c.get("id") or 0)):
        card_id, payload = card.get("id"), card.get("payload")
        if not isinstance(card_id, int) or not isinstance(payload, dict):
            continue
        name = payload.get("company") or card.get("domain")
        if opts.ungraded and is_graded(payload.get("scores")):
            continue
        if not has_people_data(payload):
            skipped += 1
            log(f"skip card {card_id} {name}: no people data to grade")
            continue
        path = opts.dir / "inputs" / f"{card_id}.json"
        path.write_text(json.dumps(grading_input(card_id, payload), indent=2, ensure_ascii=False) + "\n")
        written += 1
        log(f"export card {card_id} {name} -> {path}")
    log(f"grade-export: {written} card(s) to grade, {skipped} skipped (no people data); "
        f"write each grade to {opts.dir / 'grades'}/<card_id>.json")
    return EXIT_OK


def _clean_text(value: Any, limit: int, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GradeError(f"{what} must be a non-empty string")
    # html.unescape: a grade relayed through a tool layer can arrive with "&amp;" for "&".
    text = re.sub(r"\s+", " ", html.unescape(value)).strip()
    if len(text) > limit:
        raise GradeError(f"{what} is longer than {limit} characters")
    return text


def parse_grade(raw: str, card_id: int) -> dict[str, Any]:
    """The grader's JSON, validated against the rubric's output contract (rubric.md "Output")."""
    text = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise GradeError(f"not JSON: {e.msg}") from None
    if not isinstance(data, dict):
        raise GradeError("not a JSON object")
    if data.get("card_id") != card_id:
        raise GradeError(f"card_id {data.get('card_id')!r} is not {card_id}")
    parts = data.get("parts")
    if not isinstance(parts, dict) or set(parts) != set(PART_MAX):
        raise GradeError(f"parts must have exactly {sorted(PART_MAX)}")
    for key, top in PART_MAX.items():
        v = parts[key]
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= top:
            raise GradeError(f"parts.{key} must be an integer 0-{top}")
    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or score != sum(parts.values()):
        raise GradeError(f"score {score!r} must equal the sum of the parts ({sum(parts.values())})")
    if data.get("confidence") not in CONFIDENCES:
        raise GradeError(f"confidence must be one of {CONFIDENCES}")
    reasons = data.get("reasons")
    if not isinstance(reasons, list) or not 1 <= len(reasons) <= MAX_REASONS:
        raise GradeError(f"reasons must be a list of 1-{MAX_REASONS} strings")
    return {
        "score": score,
        "parts": {k: parts[k] for k in PART_MAX},
        "confidence": data["confidence"],
        "industry": _clean_text(data.get("industry"), MAX_INDUSTRY_CHARS, "industry"),
        "reasons": [_clean_text(r, MAX_REASON_CHARS, "a reason") for r in reasons],
    }


def describe(company: str, old: dict[str, Any], new: dict[str, Any]) -> str:
    """``Poseidon Aerospace: talent 21→72 (AI v1, high: leaders 27/40 + industry 22/25 + team 18/25 + record 5/10; rules 21)``."""
    ai, p = new["talent_ai"], new["talent_ai"]["parts"]
    return (f"{company}: talent {old.get('talent')}→{new['talent']} (AI {ai['rubric_version']}, {ai['confidence']}: "
            f"leaders {p['leaders']}/40 + industry {p['industry']}/25 + team {p['team']}/25 + "
            f"record {p['track_record']}/10; rules {new.get('talent_rules')})")


def apply(dir_: Path, deps: Deps, *, dry_run: bool, graded_at: str) -> int:
    log = deps.log
    inputs = sorted((dir_ / "inputs").glob("*.json"), key=lambda p: int(p.stem)) if (dir_ / "inputs").is_dir() else []
    if not inputs:
        log(f"grade-apply: no inputs under {dir_ / 'inputs'} (run grade-export first)")
        return EXIT_ERROR
    applied = missing = invalid = gone = errors = 0
    rows: list[dict[str, Any]] = []
    for in_path in inputs:
        card_id = int(in_path.stem)
        domain = json.loads(in_path.read_text()).get("domain")
        grade_path = dir_ / "grades" / f"{card_id}.json"
        if not grade_path.exists():
            missing += 1
            log(f"missing   card {card_id} {domain}: no grade written; it keeps its rule-based Talent")
            continue
        try:
            grade = parse_grade(grade_path.read_text(), card_id)
        except GradeError as e:
            invalid += 1
            log(f"invalid   card {card_id} {domain}: {e}; it keeps its rule-based Talent")
            continue
        found = [c for c in deps.backend.cards(domains=[domain], statuses=LIVE_STATUSES) if c.get("id") == card_id]
        if not found:
            gone += 1
            log(f"gone      card {card_id} {domain}: no longer a live card")
            continue
        payload = found[0]["payload"]
        old = payload["scores"]
        new_scores = with_ai_grade(old, {**grade, "rubric_version": RUBRIC_VERSION, "graded_at": graded_at})
        line = describe(str(payload.get("company") or domain), old, new_scores)
        rows.append({"card_id": card_id, "domain": domain, "company": payload.get("company"),
                     "talent_before": old.get("talent"), "talent_rules": new_scores.get("talent_rules"),
                     "talent_ai": grade["score"], "parts": grade["parts"], "confidence": grade["confidence"],
                     "industry": grade["industry"], "reasons": grade["reasons"]})
        if not dry_run:
            try:
                deps.backend.put_payload(card_id, {**payload, "scores": new_scores})
            except CardGone:
                gone += 1
                log(f"gone      card {card_id} {line}: deleted meanwhile")
                continue
            except (BackendError, httpx.HTTPError) as e:
                errors += 1
                log(f"error     card {card_id} {line}: {type(e).__name__}: {e}")
                continue
        applied += 1
        log(f"{'would apply' if dry_run else 'applied'} card {card_id} {line}")
    (dir_ / "results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    head = "grade-apply (dry run, nothing written): would apply" if dry_run else "grade-apply: applied"
    log(f"{head} {applied}, missing {missing}, invalid {invalid}, gone {gone}, errors {errors}")
    return EXIT_ERROR if errors else EXIT_OK


__all__ = ["RUBRIC_VERSION", "ExportOptions", "GradeError", "apply", "export", "grading_input",
           "is_graded", "parse_grade"]
