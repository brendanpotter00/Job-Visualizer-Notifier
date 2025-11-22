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
        }
    },
    {
        id: 'andurilindustries',
        name: 'Anduril',
        ats: 'greenhouse',
        config: {
            type: 'greenhouse',
            boardToken: 'andurilindustries',
        }
    },
    {
        id: 'airbnb',
        name: 'Airbnb',
        ats: 'greenhouse',
        config: {
            type: 'greenhouse',
            boardToken: 'airbnb',
        }
    },
    {
        id: 'figma',
        name: 'Figma',
        ats: 'greenhouse',
        config: {
            type: 'greenhouse',
            boardToken: 'figma',
        }
    },
    {
        id: 'palantir',
        name: 'Palantir',
        ats: 'lever',
        config: {
            type: 'lever',
            companyId: 'palantir',
            jobsUrl: 'https://jobs.lever.co/palantir',
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
    {
        id: 'coinbase',
        name: 'Coinbase',
        ats: 'greenhouse',
        config: {
            type: 'greenhouse',
            boardToken: 'coinbase',
        }
    },
    {
        id: 'xai',
        name: 'XAI',
        ats: 'greenhouse',
        config: {
            type: 'greenhouse',
            boardToken: 'xai',
        }
    },
    {
        id: 'doordash',
        name: 'Doordash',
        ats: 'greenhouse',
        config: {
            type: 'greenhouse',
            boardToken: 'doordash',
        }
    },
    {
        id: 'stripe',
        name: 'Stripe',
        ats: 'greenhouse',
        config: {
            type: 'greenhouse',
            boardToken: 'stripe',
        }
    },
];

/**
 * Get company configuration by ID
 */
export function getCompanyById(id: string): Company | undefined {
  return COMPANIES.find((c) => c.id === id);
}
