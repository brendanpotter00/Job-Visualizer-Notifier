import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../app/store';
import { jobsApi } from './jobsApi';
import { computeCompleteHorizon, RECENT_JOBS_DEFAULT_WINDOW } from './keysetWalk';
import { extractErrorMessage } from '../../lib/errors';

/**
 * Select jobs for currently selected company from RTK Query cache
 */
export const selectCurrentCompanyJobsRtk = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    return result.data?.jobs || [];
  }
);

/**
 * Select loading state for current company
 */
export const selectCurrentCompanyLoadingRtk = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    return result.isLoading;
  }
);

/**
 * Select error for current company
 */
export const selectCurrentCompanyError = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    if (!result.error) return undefined;
    return extractErrorMessage(result.error, 'Unknown error');
  }
);

/**
 * Select metadata for current company
 */
export const selectCurrentCompanyMetadataRtk = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    return (
      result.data?.metadata || {
        totalCount: 0,
      }
    );
  }
);

/**
 * Whether the Recent page's keyset walk has more pages to fetch.
 *
 * True iff at least one company-chunk still holds a cursor. The backend omits
 * `X-Next-Cursor` at the end of a walk and that absence is the only end-of-walk
 * signal, so an empty `cursors` map is definitive — it means "stop", not
 * "unknown". Pairs with `fetchNextJobsPage`; ticket 1.4's scroll trigger reads
 * this to decide whether loading more is worthwhile.
 */
export const selectHasMoreJobs = createSelector(
  [(state: RootState) => jobsApi.endpoints.getAllJobs.select()(state).data?.cursors],
  (cursors) => Object.keys(cursors ?? {}).length > 0
);

/**
 * The `firstSeenAt` cutoff at or above which the merged multi-chunk result set
 * is provably complete; `null` when the whole walk is finished (no clamp).
 *
 * See `computeCompleteHorizon` for the math and why an unclamped merge of
 * ragged chunks is a correctness bug, not a cosmetic one.
 */
export const selectCompleteHorizon = createSelector(
  [
    (state: RootState) => jobsApi.endpoints.getAllJobs.select()(state).data?.cursors,
    (state: RootState) => jobsApi.endpoints.getAllJobs.select()(state).data?.chunkFloors,
  ],
  (cursors, chunkFloors) => computeCompleteHorizon(cursors, chunkFloors)
);

/** The window the current walk is bounded by. */
export const selectJobsWindowKey = createSelector(
  [(state: RootState) => jobsApi.endpoints.getAllJobs.select()(state).data?.windowKey],
  (windowKey) => windowKey ?? RECENT_JOBS_DEFAULT_WINDOW
);

/**
 * Select jobs for a specific company (parameterized selector)
 * Usage: useAppSelector(state => selectJobsForCompany(state, companyId))
 */
export const selectJobsForCompany = createSelector(
  [(_state: RootState, companyId: string) => companyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    return result.data?.jobs || [];
  }
);
