import type { GemConfig } from '../../types';
import type { GemJobResponse } from '../types';
import { createAPIClient, type ATSCompanyConfig } from './baseClient';
import { transformGemJob } from '../transformers/gemTransformer';

/**
 * Gem job board API client.
 * Uses base client factory — Gem returns a plain array (like Lever).
 */
export const gemClient = createAPIClient<GemJobResponse[], GemConfig>({
  name: 'Gem',

  buildUrl: (config) => {
    const baseUrl = config.apiBaseUrl || '/api/gem';
    return `${baseUrl}/job_board/v0/${config.vanityUrlPath}/job_posts`;
  },

  extractJobs: (response) => response,

  transformer: transformGemJob,

  getIdentifier: (config) => config.vanityUrlPath,

  validateConfig: (config: ATSCompanyConfig): config is GemConfig => {
    return config.type === 'gem';
  },
});
