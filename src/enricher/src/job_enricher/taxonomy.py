"""Resolve the active taxonomy SKILL.md + a stable version hash.

Every classify/judge agent reads this SKILL.md; the hash is recorded on each
enrichment for provenance and drives the MANUAL re-enrichment CLI (a bump does
NOT auto-reset rows — you run `cli reenrich --taxonomy-below <v>`). Port of
job-watcher's fit-profiles resolution.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from job_enricher.store import REPO_ROOT

logger = logging.getLogger(__name__)

SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "taxonomy" / "SKILL.md"
# D3: the long-form subcategory rubric lives in its OWN file, loaded ONLY by the
# subcategory-only backfill lane (build_subcategory_prompt) and the eval
# pre-labeller. It is NEVER inlined into the classify or judge prompt — the whole
# point of the split is that the classify lane pays for the compact section 1b
# and nothing more.
SUBCATEGORY_RUBRIC_PATH = (
    REPO_ROOT / ".claude" / "skills" / "taxonomy" / "SUBCATEGORIES.md"
)
_VERSION_RE = re.compile(r"^version:\s*(\S+)\s*$", re.MULTILINE)

# Canonical slug sets — the SINGLE source of truth for valid category/level
# slugs. These MUST equal JVN's enums exactly (see the Contract of Record); a
# slug outside these sets is a hallucination that JVN would soft-null, so it is
# caught locally before write-back (see validate_facets). eval/scoring.py imports
# these so there is exactly one definition.
CATEGORIES: frozenset[str] = frozenset(
    {
        "software_engineering",
        "hardware_engineer",
        "product_manager",
        "data_scientist",
        "growth",
        "business_ops",
    }
)
LEVELS: frozenset[str] = frozenset(
    {"intern", "new_grad", "entry", "mid", "senior", "senior_plus", "manager"}
)

# --- Subcategories (SWE sub-specialties) -------------------------------------
# EXACTLY these 17 slugs, alphabetical (which for this set is also
# label-alphabetical). Byte-identical in six places: JVN's seed migration, JVN's
# SUBCATEGORY_SLUGS, the frontend FALLBACK_SUBCATEGORIES, this frozenset,
# `ollama._SUBCATEGORY_SCHEMA`'s enum and SKILL.md section 1b. ENR-PAR-1 asserts
# the intra-repo half, ENR-PAR-2 the cross-repo half.
#
# `growth_engineering` and `product_engineering` joined in the 15 -> 17 widening.
# Both slot in WITHOUT disturbing any existing slug's relative order, but they DO
# shift nine `sort_order` values (everything from `infrastructure_platform` on),
# so JVN's seeded rows have to be re-emitted, not appended to.
SUBCATEGORIES: frozenset[str] = frozenset(
    {
        "ai_engineering",
        "backend",
        "data_engineering",
        "devops_sre",
        "embedded_systems",
        "forward_deployed",
        "frontend",
        "full_stack",
        "growth_engineering",
        "infrastructure_platform",
        "ml_engineering",
        "mobile",
        "product_engineering",
        "qa_testing",
        "quantitative",
        "robotics_autonomy",
        "security",
    }
)

# Subcategories only ever hang off ONE category. The arrow never runs backwards:
# a subcategory can never pull a row INTO software_engineering.
SUBCATEGORY_PARENT = "software_engineering"

# An ordered list, primary first, at most this many.
MAX_SUBCATEGORIES = 2

# `full_stack` is EXCLUSIVE: it means the role explicitly owns both halves, so
# emitting it beside either half silently widens every filter that matches
# either one, and no downstream code can reconstruct the intent.
_FULL_STACK_SUPPRESSES: frozenset[str] = frozenset({"frontend", "backend"})

# The five (and only five) provenances a stored subcategory list can carry.
#   rule     - deterministic title/tag regex, no model call
#   classify - the live Tier-1 classify tick
#   backfill - the Tier-2 subcategory-only lane
#   judge    - the judge overwrote the classify answer
#   human    - an admin correction; the value the D2 push treats as a LOCK
# There is deliberately no `backfill_failed`: a failed row stays NULL with only
# `subcategory_attempts` bumped, so it has no source.
SUBCATEGORY_SOURCES: frozenset[str] = frozenset(
    {"rule", "classify", "backfill", "judge", "human"}
)


def validate_subcategories(
    category: str | None, value: Any
) -> tuple[list[str] | None, list[tuple[str, str]], list[str]]:
    """Validate a model-emitted ``subcategories`` value against the contract.

    The rules live HERE, in code, because a prompt is not a rail. Never raises —
    a malformed value must never crash a tick.

    Returns ``(subcategories, bad, warnings)``:

    * ``subcategories`` is ``None`` (never evaluated — **this IS the backfill
      queue**), ``[]`` (evaluated, no specialty applies — TERMINAL) or an ordered
      1-2 element list. The tri-state is load-bearing and must never be collapsed.
    * ``bad`` is ``(facet, offending_value)`` pairs — hallucinations. The caller
      folds these into the SAME needs_human path ``validate_facets``' ``bad``
      already drives.
    * ``warnings`` are RULE APPLICATIONS (truncation, a full_stack suppression),
      never hallucinations. A warning must NEVER set ``needs_human``.
    """
    warnings: list[str] = []
    if value is None:
        return None, [], warnings
    if isinstance(value, str):
        # Tolerantly wrap a bare string; a single slug is a common model shape.
        value = [value]
    # bool is an int subclass, so it must be rejected explicitly by the isinstance
    # check below rather than slipping through any numeric tolerance.
    if not isinstance(value, list):
        return None, [("subcategories", repr(value))], warnings

    bad: list[tuple[str, str]] = []
    slugs: list[str] = []
    for element in value:
        if not isinstance(element, str):
            bad.append(("subcategories", repr(element)))
            continue
        if element not in SUBCATEGORIES:
            bad.append(("subcategories", element))
            continue
        if element not in slugs:  # dedup, preserving first-seen order
            slugs.append(element)

    if "full_stack" in slugs and any(s in _FULL_STACK_SUPPRESSES for s in slugs):
        suppressed = [s for s in slugs if s in _FULL_STACK_SUPPRESSES]
        slugs = [s for s in slugs if s not in _FULL_STACK_SUPPRESSES]
        warnings.append(
            "full_stack is exclusive; dropped " + ", ".join(suppressed)
        )

    if len(slugs) > MAX_SUBCATEGORIES:
        warnings.append(
            f"truncated {len(slugs)} subcategories to {MAX_SUBCATEGORIES}: "
            + ", ".join(slugs[MAX_SUBCATEGORIES:])
        )
        slugs = slugs[:MAX_SUBCATEGORIES]

    # THE LEAK RULE. A subcategory on a non-SWE row (including an unresolved
    # `category is None`) is a hallucination, not a rule application — it is what
    # makes `subcategory_leak_rate` structurally zero in production while staying
    # measurable on raw model output in eval.
    #
    # ⚠ GATED ON `value` (WHAT THE MODEL SUPPLIED), NOT ON `slugs` (what survived
    # validation). Gating on `slugs` split this branch in two: a non-SWE row whose
    # subcategories were ALL invalid emptied `slugs`, the rule never fired, and the
    # function returned `[]` — TERMINAL, "evaluated, none apply" — while the SAME
    # row with a VALID slug returned None. A hallucinated slug on a row that is not
    # even software_engineering must never be the thing that marks a row evaluated
    # for good; it is the identical leak either way, so it gets the identical answer.
    #
    # An EXPLICIT `[]` on a non-SWE row is untouched by this (`value` is falsy) —
    # that is RAIL D's deliberate output in `cli._merge_judge`, which forces `[]`
    # precisely so a non-SWE row LEAVES the backfill queue.
    if category != SUBCATEGORY_PARENT and value:
        # `bad` carries the RAW offending value (a list), matching the contract's
        # stated shape `(None, [('subcategories', ['backend'])], [])`.
        return None, [("subcategories", value)], []

    return slugs, bad, warnings


def validate_facets(
    category: str | None, level: str | None
) -> tuple[str | None, str | None, list[tuple[str, str]]]:
    """Validate a classify/judge result's ``category``/``level`` against the
    canonical slug sets.

    A slug not in the set is a hallucination JVN would silently null while still
    marking the job done. To catch it locally we NULL the offending slug (so the
    bad value is never shipped) and return it in ``bad`` so the caller can flag
    the row ``needs_human`` and log the drop. Does not raise — a bad slug must
    never crash a tick.

    Returns ``(category, level, bad)`` where ``bad`` is a list of
    ``(facet_name, offending_value)`` pairs (empty when both slugs are valid).
    """
    bad: list[tuple[str, str]] = []
    if category is not None and category not in CATEGORIES:
        bad.append(("category", category))
        category = None
    if level is not None and level not in LEVELS:
        bad.append(("level", level))
        level = None
    return category, level, bad


def skill_path() -> Path:
    return SKILL_PATH


def read_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def subcategory_rubric_path() -> Path:
    return SUBCATEGORY_RUBRIC_PATH


def read_subcategory_rubric() -> str:
    """The long-form subcategory rubric. RAISES FileNotFoundError when missing.

    ⚠ It must RAISE, not return ''. A silent empty rubric is the failure mode
    that makes the backfill lane label from nothing — every row comes back `[]`
    or garbage, the run reports success, and the coverage number that gates the
    90% reveal becomes a lie. Mirrors read_skill() exactly: an uncached plain
    read_text.

    Both of taxonomy_version()'s guarded callers already wrap OSError, and
    FileNotFoundError is an OSError subclass, so a missing rubric degrades there
    exactly as a missing SKILL.md already does. `cli health` asserts both files
    exist, so the deploy sanity check catches it, not the first classify."""
    return SUBCATEGORY_RUBRIC_PATH.read_text(encoding="utf-8")


def declared_version(text: str | None = None) -> str:
    """The `version:` from the frontmatter (human-facing tag, e.g. 'v1')."""
    body = text if text is not None else read_skill()
    m = _VERSION_RE.search(body)
    return m.group(1) if m else "v0"


def content_hash(text: str | None = None) -> str:
    """Short stable hash of SKILL.md alone — DELIBERATELY UNCHANGED by D3.

    ⚠ Leave this SKILL.md-only. The v6 eval baseline must stay reproducible from
    a git blob (`git show <SKILL_MD_V6_GIT_SHA>:.claude/skills/taxonomy/SKILL.md`),
    which is only possible while this function hashes exactly that one file.
    `taxonomy_version()` is what widens to cover both files."""
    body = text if text is not None else read_skill()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def combined_hash() -> str:
    """Short stable hash over BOTH taxonomy files, NUL-separated.

    ⚠ This is what closes the hole D3 would otherwise open: with a SKILL.md-only
    hash, editing SUBCATEGORIES.md would change the rubric that produced a label
    WITHOUT moving the version recorded beside it — provenance that quietly lies.
    The NUL separator makes the concatenation unambiguous."""
    body = read_skill() + "\x00" + read_subcategory_rubric()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def taxonomy_version() -> str:
    """Combined tag stored on each enrichment, e.g. 'v7+3f9a1c2b8e04'.

    Keeps the `v<N>+<hash>` shape, so `_TAXONOMY_VERSION_RE` and `_version_below`
    are untouched. ⚠ CONSEQUENCE, from v7 on: a RUBRIC-ONLY edit moves the hash
    and not the declared N, and same-N-different-hash is NOT below — so
    `reenrich --taxonomy-below` will never pick a rubric edit up. Intended; see
    `_version_below`'s docstring."""
    text = read_skill()
    return f"{declared_version(text)}+{combined_hash()}"
