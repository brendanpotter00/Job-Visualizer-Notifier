import type { FetchProgress, CompanyFetchStatus } from '../../types';

/**
 * Update progress tracking for a single company
 *
 * Mutates the progress object to update a company's status and metadata.
 * Automatically increments the completed count when transitioning to a terminal state.
 *
 * @param progress - The progress tracking object (mutated in place)
 * @param companyId - The company identifier to update
 * @param updates - Status and optional metadata updates
 *
 * @example
 * ```typescript
 * // Mark company as loading
 * updateCompanyProgress(draft.progress, 'acme', { status: 'loading' });
 *
 * // Mark company as successful with job count
 * updateCompanyProgress(draft.progress, 'acme', {
 *   status: 'success',
 *   jobCount: 42,
 * });
 *
 * // Mark company as failed with error
 * updateCompanyProgress(draft.progress, 'acme', {
 *   status: 'error',
 *   error: 'Network timeout',
 * });
 * ```
 */
export function updateCompanyProgress(
  progress: FetchProgress,
  companyId: string,
  updates: {
    status: CompanyFetchStatus;
    error?: string;
    jobCount?: number;
  }
): void {
  const company = progress.companies.find((c) => c.companyId === companyId);

  if (!company) {
    return;
  }

  // Update status
  company.status = updates.status;

  // Set completion timestamp for terminal states
  if (updates.status === 'success' || updates.status === 'error') {
    company.completedAt = new Date().toISOString();
    progress.completed += 1;
  }

  // Set optional metadata
  if (updates.error !== undefined) {
    company.error = updates.error;
  }

  if (updates.jobCount !== undefined) {
    company.jobCount = updates.jobCount;
  }
}
