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

export function validateSearchJobsResponse(body: unknown): ValidatedSearchJobsBody {
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

  return {
    jobs: body.jobs as unknown as BackendJobListing[],
    nextCursor: (body.nextCursor as string | null | undefined) ?? null,
    // `meta` is null on cursor pages by design, so only a present, non-null value
    // is validated.
    counts: body.meta == null ? undefined : validateCounts(body.meta),
  };
}
