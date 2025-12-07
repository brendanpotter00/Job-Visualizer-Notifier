import type { LeverConfig } from '../../types';
import type { LeverJobResponse } from '../types';
import { createAPIClient, type ATSCompanyConfig } from './baseClient';
import { transformLeverJob } from '../transformers/leverTransformer';

/**
 * Lever postings API client
 * Uses base client factory to eliminate code duplication
 */
export const leverClient = createAPIClient<LeverJobResponse[], LeverConfig>({
  name: 'Lever',

  buildUrl: (config) => {
    const baseUrl = config.apiBaseUrl || '/api/lever';
    return `${baseUrl}/v0/postings/${config.companyId}`;
  },

  extractJobs: (response) => response, // Lever API returns array directly

  transformer: transformLeverJob,

  getIdentifier: (config) => config.companyId,

  validateConfig: (config: ATSCompanyConfig): config is LeverConfig => {
    return config.type === 'lever';
  },
});
