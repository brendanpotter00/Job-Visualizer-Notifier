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

from job_enricher.store import REPO_ROOT

logger = logging.getLogger(__name__)

SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "taxonomy" / "SKILL.md"
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
        "project_manager",
        "data_scientist",
        "growth",
        "business_ops",
    }
)
LEVELS: frozenset[str] = frozenset(
    {"new_grad", "entry", "mid", "senior", "senior_plus", "manager"}
)


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


def declared_version(text: str | None = None) -> str:
    """The `version:` from the frontmatter (human-facing tag, e.g. 'v1')."""
    body = text if text is not None else read_skill()
    m = _VERSION_RE.search(body)
    return m.group(1) if m else "v0"


def content_hash(text: str | None = None) -> str:
    """Short stable hash of the full file — the real provenance key."""
    body = text if text is not None else read_skill()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def taxonomy_version() -> str:
    """Combined tag stored on each enrichment, e.g. 'v1+3f9a1c2b8e04'."""
    text = read_skill()
    return f"{declared_version(text)}+{content_hash(text)}"
