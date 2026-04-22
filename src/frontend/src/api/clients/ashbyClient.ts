import type { AshbyConfig } from '../../types';
import type { AshbyAPIResponse } from '../types';
import { createAPIClient, type ATSCompanyConfig } from './baseClient';
import { transformAshbyJob } from '../transformers/ashbyTransformer';
import { rewriteCursorJobUrls } from './cursorJobUrl';

/**
 * Ashby job posting API client
 * Uses base client factory to eliminate code duplication
 */
export const ashbyClient = createAPIClient<AshbyAPIResponse, AshbyConfig>({
  name: 'Ashby',

  buildUrl: (config) => {
    const baseUrl = config.apiBaseUrl || '/api/ashby';
    return `${baseUrl}/posting-api/job-board/${config.jobBoardName}?includeCompensation=true`;
  },

  extractJobs: (response) => rewriteCursorJobUrls(response.jobs),

  transformer: transformAshbyJob,

  getIdentifier: (config) => config.jobBoardName,

  validateConfig: (config: ATSCompanyConfig): config is AshbyConfig => {
    return config.type === 'ashby';
  },
});
