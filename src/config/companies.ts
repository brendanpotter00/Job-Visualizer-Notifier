import type { Company } from '../types';

/**
 * Company configurations for multi-ATS support
 */
export const COMPANIES: Company[] = [
  {
    id: 'spacex',
    name: 'SpaceX',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'spacex',
    },
  },
  {
    id: 'nominal',
    name: 'Nominal',
    ats: 'lever',
    config: {
      type: 'lever',
      companyId: 'nominal',
      jobsUrl: 'https://jobs.lever.co/nominal',
    },
  },
];

/**
 * Get company configuration by ID
 */
export function getCompanyById(id: string): Company | undefined {
  return COMPANIES.find((c) => c.id === id);
}
