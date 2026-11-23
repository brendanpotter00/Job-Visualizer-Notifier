#!/usr/bin/env bash
# ENR-PAR-2 (b) — the SCHEDULED, LIVE cross-repo taxonomy parity check.
#
# GETs JVN's /api/jobs/facets, compares it against this repo's
# taxonomy.CATEGORIES / taxonomy.SUBCATEGORIES / taxonomy.SUBCATEGORY_SOURCES,
# exits non-zero on ANY mismatch, and texts on divergence.
#
# It refreshes golden/taxonomy-parity/jvn_facets.json (+ its .sha256) ONLY when
# the check PASSES. Writing on a divergence would overwrite the vendored
# "verbatim JVN copy" with the drifted live data -- a watchdog erasing the
# evidence it exists to catch, and permanently masking that drift from the
# PR-blocking offline half. Mirrors the existing com.bp.jvn-health-watch
# precedent: the drift this catches is slow, silent and only observable in
# production, so a scheduled job that TEXTS is the right shape.
#
# Env:
#   JVN_BASE_URL                 required, e.g. https://onesecondswe.dev
#   ALLOW_EMPTY_SUBCATEGORIES=1  tolerate zero subcategories (Phase-1 window,
#                                before SCHEMA-7 seeds the 17 rows)
#   PARITY_CHECK=1               required, so a stray run cannot text by accident
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ "${PARITY_CHECK:-}" != "1" ]]; then
  echo "check_taxonomy_parity: set PARITY_CHECK=1 to run" >&2
  exit 2
fi
if [[ -z "${JVN_BASE_URL:-}" ]]; then
  echo "check_taxonomy_parity: JVN_BASE_URL is not set" >&2
  exit 2
fi

args=(--base-url "$JVN_BASE_URL" --write-snapshot --text-on-divergence)
if [[ "${ALLOW_EMPTY_SUBCATEGORIES:-}" == "1" ]]; then
  args+=(--allow-empty-subcategories)
fi

exec uv run python -m job_enricher.cli parity-check "${args[@]}"
