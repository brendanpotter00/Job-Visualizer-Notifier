/**
 * Runtime validation for the `GET /api/jobs/search` envelope.
 *
 * Job rows were the least-validated payload in the app: `fetchJobsPage` cast the
 * parsed body straight to `BackendJobListing[]` with no checks, so a 2xx body of
 * the wrong shape (a CDN error page, a serializer regression, a proxy returning
 * HTML) reached the transformer and surfaced as a scatter of `undefined`s in the
 * UI rather than as an error. This closes that on the new endpoint, following the
 * fail-loud pattern `validateLocationSearchResults` already established.
 *
 * Deliberately checks only the fields the list is load-bearing on. A stricter
 * check would reject a backward-compatible additive change to the response for no
 * benefit; a looser one would let the failure through.
 */

import type { BackendJobListing } from '../../api/types.ts';
import type { SearchJobsCounts, SearchJobsResponseBody } from './searchJobsTypes.ts';
import { logger } from '../../lib/logger.ts';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): boolean {
  return value === null || value === undefined || typeof value === 'string';
}

function validateCounts(value: unknown): SearchJobsCounts {
  if (
    !isRecord(value) ||
    typeof value.filteredTotal !== 'number' ||
    typeof value.countLast24h !== 'number' ||
    typeof value.countLast3h !== 'number'
  ) {
    throw new Error('Invalid /api/jobs/search response: bad meta shape');
  }
  return {
    total: value.filteredTotal,
    last24h: value.countLast24h,
    last3h: value.countLast3h,
  };
}

export interface ValidatedSearchJobsBody extends SearchJobsResponseBody {
  counts?: SearchJobsCounts;
}

export interface ValidateSearchJobsOptions {
  /**
   * Whether this body answers the FIRST request of a walk (`cursor === null`).
   *
   * Load-bearing, and the validator cannot derive it: `meta` is absent on every
   * cursor page BY DESIGN (the counts describe the filter set, not the page, so
   * the endpoint computes them once), and absent on page 1 only when something
   * went wrong. Those two are indistinguishable in the body — the caller is the
   * only party that knows which request it made.
   */
  isFirstPage: boolean;
}

export function validateSearchJobsResponse(
  body: unknown,
  { isFirstPage }: ValidateSearchJobsOptions
): ValidatedSearchJobsBody {
  if (!isRecord(body)) {
    throw new Error('Invalid /api/jobs/search response: body is not an object');
  }
  if (!Array.isArray(body.jobs)) {
    throw new Error('Invalid /api/jobs/search response: jobs is not an array');
  }
  // `undefined` is tolerated as "no more pages" alongside an explicit null: a
  // missing key and a null key mean the same thing to every caller, and treating
  // the absence as an error would make the contract needlessly brittle.
  if (body.nextCursor !== null && body.nextCursor !== undefined && typeof body.nextCursor !== 'string') {
    throw new Error('Invalid /api/jobs/search response: nextCursor is not a string or null');
  }
  for (const row of body.jobs) {
    if (
      !isRecord(row) ||
      typeof row.id !== 'string' ||
      typeof row.title !== 'string' ||
      typeof row.company !== 'string' ||
      typeof row.url !== 'string' ||
      typeof row.sourceId !== 'string' ||
      typeof row.firstSeenAt !== 'string' ||
      !isNullableString(row.location) ||
      !isNullableString(row.category) ||
      !isNullableString(row.level)
    ) {
      throw new Error('Invalid /api/jobs/search response: bad job row shape');
    }
  }

  if (isFirstPage && body.meta == null) {
    // LOGGED, not thrown, and the asymmetry is deliberate.
    //
    // The endpoint sends `meta` on page 1 unconditionally (`jobs_search.py`:
    // `if parsed_cursor is None`), so its absence here is a broken contract —
    // a serializer regression, or a proxy/CDN that rewrote the envelope. The
    // consequence is not loud: `counts` stays undefined, the header tiles render
    // em-dashes and `aria-setsize` becomes -1 (ARIA's "unknown"), which is the
    // CORRECT degradation and is why this must not throw. Throwing would blank a
    // page whose rows are perfectly good.
    //
    // But degrading silently is how a permanent regression stays invisible: the
    // page looks deliberate, nothing errors, and the only symptom is three
    // dashes nobody files a bug about. So the fact goes to the log — this is the
    // one contract violation on this endpoint that produced no diagnostic
    // anywhere. Every OTHER shape problem in this file throws.
    logger.error(
      '[jobsApi] /api/jobs/search page 1 came back without `meta`:',
      'header counts unavailable; tiles will render as em-dashes and aria-setsize as -1 ' +
        'until a new page 1 lands'
    );
  }

  return {
    jobs: body.jobs as unknown as BackendJobListing[],
    nextCursor: (body.nextCursor as string | null | undefined) ?? null,
    // The wire key is `meta`; `counts` is this module's normalized name for it
    // (see `SearchJobsResponseBody`). `meta` is null on cursor pages by design, so
    // only a present, non-null value is validated.
    counts: body.meta == null ? undefined : validateCounts(body.meta),
  };
}
