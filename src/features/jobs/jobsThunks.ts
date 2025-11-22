import { createAsyncThunk } from '@reduxjs/toolkit';
import type { TimeWindow } from '../../types';
import { getCompanyById } from '../../config/companies';
import { greenhouseClient } from '../../api/greenhouseClient';
import { leverClient } from '../../api/leverClient';
import { APIError } from '../../api/types';
import { calculateSinceTimestamp } from '../../utils/dateUtils';

interface LoadJobsParams {
  companyId: string;
  timeWindow: TimeWindow;
}

/**
 * Async thunk to load jobs for a company
 */
export const loadJobsForCompany = createAsyncThunk(
  'jobs/loadJobsForCompany',
  async ({ companyId, timeWindow }: LoadJobsParams, { signal, rejectWithValue }) => {
    const company = getCompanyById(companyId);

    if (!company) {
      return rejectWithValue(`Company not found: ${companyId}`);
    }

    // Calculate 'since' timestamp based on time window
    const since = calculateSinceTimestamp(timeWindow);

    try {
      // Select appropriate client based on ATS type
      const client = company.ats === 'greenhouse' ? greenhouseClient : leverClient;

      const result = await client.fetchJobs(company.config, {
        since,
        signal,
      });

      // Calculate date range
      const dates = result.jobs.map((job) => new Date(job.createdAt).getTime());
      const oldestJobDate = dates.length > 0 ? new Date(Math.min(...dates)).toISOString() : undefined;
      const newestJobDate = dates.length > 0 ? new Date(Math.max(...dates)).toISOString() : undefined;

      return {
        companyId,
        jobs: result.jobs,
        metadata: {
          ...result.metadata,
          oldestJobDate,
          newestJobDate,
        },
      };
    } catch (error) {
      if (error instanceof APIError) {
        return rejectWithValue({
          message: error.message,
          statusCode: error.statusCode,
          retryable: error.retryable,
        });
      }
      return rejectWithValue({ message: 'Unknown error occurred' });
    }
  }
);
