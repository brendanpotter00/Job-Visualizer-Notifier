"""What "this job has a description" means, in one place.

``job_listings.details_scraped`` is supposed to mean "we have this job's detail
content, not just its list-view stub". Every ATS client hard-coded it to ``True``
regardless, so it was true for all 1,246 Cisco, 613 Intel and 11,901 Workday rows whose
``description_html`` is JSON ``null``, and for all 1,172 Netflix/Eightfold rows whose
list payload carries no description key at all — verified against prod, where 100% of
every Workday and Eightfold company's rows are flagged and 100% of them have no
description. A flag that is true for every row carries no information; worse, it reads
as a positive assertion about rows where the opposite is true.

The five keys below are the real per-ATS storage shapes, verified against prod
2026-07-12 and already encoded in ``enrichment_monitor.DESCRIPTION_SQL`` — Ashby and
Lever store ``description_html``, Greenhouse ``content``, Gem ``content_html``, the
Apple/Microsoft scrapers ``description``, and the Google scraper's "About the job"
narrative ``about_the_job``. That SQL is the read side of exactly this predicate (it
decides what the enrichment pipeline may claim), so the two must agree;
``test_details_scraped_truthfulness.py`` fails if they drift.

Stdlib-only on purpose. This is imported by the six ATS clients, which sit inside the
Procrastinate leaf tasks' import closure — the closure an AST guard walks to prove the
replay path cannot reach a browser or an LLM.
"""

from __future__ import annotations

from typing import Any, Mapping

# Ordered to match ``enrichment_monitor.DESCRIPTION_SQL``'s COALESCE, which is the read
# side of the same question. Order is not semantically load-bearing here (any hit wins)
# but keeping it identical is what makes the drift test a one-line comparison.
DESCRIPTION_KEYS = (
    "description_html",
    "content",
    "content_html",
    "description",
    "about_the_job",
)


def has_description(details: Mapping[str, Any] | None) -> bool:
    """True when ``details`` actually carries description text under any known key.

    Truthiness, not key presence: Workday builds its ``details`` dict with an explicit
    ``"description_html": None`` so the JSONB shape matches the other ATSs, and an empty
    string is a board that published a description field and left it blank. Both mean
    "no description", and ``->>`` maps both to something ``DESCRIPTION_SQL``'s COALESCE
    falls through, so treating them as present here would put the two sides of the same
    predicate in disagreement.
    """
    if not details:
        return False
    return any(details.get(key) for key in DESCRIPTION_KEYS)
