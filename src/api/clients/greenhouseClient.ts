import type { GreenhouseConfig } from '../../types';
import type { GreenhouseAPIResponse } from '../types';
import { createAPIClient, type ATSCompanyConfig } from './baseClient';
import { transformGreenhouseJob } from '../transformers/greenhouseTransformer';

/**
 * Greenhouse job board API client
 * Uses base client factory to eliminate code duplication
 */
export const greenhouseClient = createAPIClient<GreenhouseAPIResponse, GreenhouseConfig>({
  name: 'Greenhouse',

  buildUrl: (config) => {
    const baseUrl = config.apiBaseUrl || '/api/greenhouse';
    return `${baseUrl}/v1/boards/${config.boardToken}/jobs?content=true`;
  },

  extractJobs: (response) => response.jobs,

  transformer: transformGreenhouseJob,

  getIdentifier: (config) => config.boardToken,

  validateConfig: (config: ATSCompanyConfig): config is GreenhouseConfig => {
    return config.type === 'greenhouse';
  },
});
