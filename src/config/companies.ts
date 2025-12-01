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
    jobsUrl: 'https://boards.greenhouse.io/spacex',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2230846%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=Gp2&sortBy=%22date_posted%22',
  },
  {
    id: 'andurilindustries',
    name: 'Anduril',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'andurilindustries',
    },
    jobsUrl: 'https://boards.greenhouse.io/andurilindustries',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2218293159%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=vst&sortBy=%22date_posted%22',
  },
  {
    id: 'airbnb',
    name: 'Airbnb',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'airbnb',
    },
    jobsUrl: 'https://boards.greenhouse.io/airbnb',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%22309694%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=Am6&sortBy=%22date_posted%22',
  },
  {
    id: 'figma',
    name: 'Figma',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'figma',
    },
    jobsUrl: 'https://boards.greenhouse.io/figma',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223650502%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=Hnn&sortBy=%22date_posted%22',
  },
  {
    id: 'notion',
    name: 'Notion',
    ats: 'ashby',
    config: {
      type: 'ashby',
      jobBoardName: 'notion',
    },
    jobsUrl: 'https://careers.ashbyhq.com/notion',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2230898036%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=_GL&sortBy=%22date_posted%22',
  },
  {
    id: 'neuralink',
    name: 'Neuralink',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'neuralink',
    },
    jobsUrl: 'https://boards.greenhouse.io/neuralink',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2219002862%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=6Ij&sortBy=%22date_posted%22',
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
    jobsUrl: 'https://jobs.lever.co/palantir',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2220708%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=%40ld&sortBy=%22date_posted%22',
  },
  {
    id: 'saronic',
    name: 'Saronic',
    ats: 'lever',
    config: {
      type: 'lever',
      companyId: 'saronic',
      jobsUrl: 'https://jobs.lever.co/saronic',
    },
    jobsUrl: 'https://jobs.lever.co/saronic',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2289680213%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=aOp&sortBy=%22date_posted%22',
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
    jobsUrl: 'https://jobs.lever.co/nominal',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2292924343%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=a5Q&sortBy=%22date_posted%22',
  },
  {
    id: 'coinbase',
    name: 'Coinbase',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'coinbase',
    },
    jobsUrl: 'https://boards.greenhouse.io/coinbase',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%222857634%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=65F&sortBy=%22date_posted%22',
  },
  {
    id: 'robinhood',
    name: 'Robinhood',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'robinhood',
    },
    jobsUrl: 'https://boards.greenhouse.io/robinhood',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223254263%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=AsA&sortBy=%22date_posted%22',
  },
  {
    id: 'spotify',
    name: 'Spotify',
    ats: 'lever',
    config: {
      type: 'lever',
      companyId: 'spotify',
      jobsUrl: 'https://jobs.lever.co/spotify',
    },
    jobsUrl: 'https://jobs.lever.co/spotify',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%22207470%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=%4072&sortBy=%22date_posted%22',
  },
  {
    id: 'xai',
    name: 'XAI',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'xai',
    },
    jobsUrl: 'https://boards.greenhouse.io/xai',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2296151950%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=bYM&sortBy=%22date_posted%22',
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'anthropic',
    },
    jobsUrl: 'https://boards.greenhouse.io/anthropic',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2274126343%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=L2U&sortBy=%22date_posted%22',
  },
  {
    id: 'reddit',
    name: 'Reddit',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'reddit',
    },
    jobsUrl: 'https://boards.greenhouse.io/reddit',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%22150573%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=4ar&sortBy=%22date_posted%22',
  },
  {
    id: 'cloudflare',
    name: 'Cloudflare',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'cloudflare',
    },
    jobsUrl: 'https://boards.greenhouse.io/cloudflare',
    recruiterLinkedInUrl: '',
  },
  {
    id: 'scaleai',
    name: 'ScaleAI',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'scaleai',
    },
    jobsUrl: 'https://boards.greenhouse.io/scaleai',
    recruiterLinkedInUrl: '',
  },
  {
    id: 'lyft',
    name: 'Lyft',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'lyft',
    },
    jobsUrl: 'https://boards.greenhouse.io/lyft',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%222620735%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=hp!&sortBy=%22date_posted%22',
  },
  {
    id: 'doordashusa',
    name: 'Doordash',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'doordashusa',
    },
    jobsUrl: 'https://boards.greenhouse.io/doordashusa',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223205573%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=DT%3A&sortBy=%22date_posted%22',
  },
  {
    id: 'stripe',
    name: 'Stripe',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'stripe',
    },
    jobsUrl: 'https://boards.greenhouse.io/stripe',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%222135371%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=z(2&sortBy=%22date_posted%22',
  },
  {
    id: 'ramp',
    name: 'Ramp',
    ats: 'ashby',
    config: {
      type: 'ashby',
      jobBoardName: 'ramp',
    },
    jobsUrl: 'https://careers.ashbyhq.com/ramp',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%221406226%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=e%3Ab&sortBy=%22date_posted%22',
  },
  {
    id: 'snowflake',
    name: 'Snowflake',
    ats: 'ashby',
    config: {
      type: 'ashby',
      jobBoardName: 'ramp',
    },
    jobsUrl: 'https://careers.ashbyhq.com/snowflake',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223653845%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=4o9&sortBy=%22date_posted%22',
  },
  {
    id: 'plaid',
    name: 'Plaid',
    ats: 'lever',
    config: {
      type: 'lever',
      companyId: 'plaid',
      jobsUrl: 'https://jobs.lever.co/plaid',
    },
    jobsUrl: 'https://jobs.lever.co/plaid',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%222684737%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=8n%3B&sortBy=%22date_posted%22',
  },
  {
    id: 'appliedintuition',
    name: 'Applied Intuition',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'appliedintuition',
    },
    jobsUrl: 'https://boards.greenhouse.io/appliedintuition',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2218808325%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=Pz-&sortBy=%22date_posted%22',
  },
  {
    id: 'discord',
    name: 'Discord',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'discord',
    },
    jobsUrl: 'https://boards.greenhouse.io/discord',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223765675%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=P0b&sortBy=%22date_posted%22',
  },
  {
    id: 'brex',
    name: 'Brex',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'brex',
    },
    jobsUrl: 'https://boards.greenhouse.io/brex',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2218505670%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=o-E&sortBy=%22date_posted%22',
  },
  {
    id: 'Squarespace',
    name: 'squarespace',
    ats: 'greenhouse',
    config: {
      type: 'greenhouse',
      boardToken: 'squarespace',
    },
    jobsUrl: 'https://boards.greenhouse.io/squarespace',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%22265314%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=JwA&sortBy=%22date_posted%22',
  },
  {
    id: 'nvidia',
    name: 'NVIDIA',
    ats: 'workday',
    config: {
      type: 'workday',
      baseUrl: 'https://nvidia.wd5.myworkdayjobs.com',
      tenantSlug: 'nvidia',
      careerSiteSlug: 'NVIDIAExternalCareerSite',
      jobsUrl: 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details',
      // Default facet filters - restricts to US Engineering full-time positions
      defaultFacets: {
        locationHierarchy1: ['2fcb99c455831013ea52fb338f2932d8'], // United States
        jobFamilyGroup: ['0c40f6bd1d8f10ae43ffaefd46dc7e78'], // Engineering
        timeType: ['5509c0b5959810ac0029943377d47364'], // Full time
      },
    },
    jobsUrl: 'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/details',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223608%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=YU9&sortBy=%22date_posted%22',
  },
  {
    id: 'adobe',
    name: 'Adobe',
    ats: 'workday',
    config: {
      type: 'workday',
      baseUrl: 'https://adobe.wd5.myworkdayjobs.com',
      tenantSlug: 'adobe',
      careerSiteSlug: 'external_experienced',
      jobsUrl: 'https://adobe.wd5.myworkdayjobs.com/external_experienced/details',
      // Default facet filters - restricts to US Engineering full-time positions
      defaultFacets: {
        locationCountry: ['bc33aa3152ec42d4995f4791a106ed09'], // United States
        jobFamilyGroup: ['591af8b812fa10737af39db3d96eed9f', '591af8b812fa10737b43a1662896f01c'], // Engineering, University
      },
    },
    jobsUrl: 'https://adobe.wd5.myworkdayjobs.com/external_experienced/details',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%221480%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=!%3BQ&sortBy=%22date_posted%22',
  },
  // {
  //     id: 'netflix',
  //     name: 'Netflix',
  //     ats: 'workday',
  //     config: {
  //         type: 'workday',
  //         baseUrl: 'https://netflix.wd1.myworkdayjobs.com',
  //         tenantSlug: 'Netflix',
  //         careerSiteSlug: 'Netflix',
  //         jobsUrl: 'https://netflix.wd1.myworkdayjobs.com/Netflix/details',
  //         // Default facet filters - restricts to US Engineering full-time positions
  //         defaultFacets: {
  //             // locationCountry: ['bc33aa3152ec42d4995f4791a106ed09'], // United States
  //             // jobFamilyGroup: ['591af8b812fa10737af39db3d96eed9f', '591af8b812fa10737b43a1662896f01c'], // Engineering, University
  //         },
  //     },
  //     jobsUrl: 'https://netflix.wd1.myworkdayjobs.com/Netflix/details',
  //     recruiterLinkedInUrl: '',
  // },
];

export const enum CompanyId {
  Spacex = 'spacex',
  AndurilIndustries = 'andurilindustries',
  Airbnb = 'airbnb',
  Figma = 'figma',
  Notion = 'notion',
  Neuralink = 'neuralink',
  Palantir = 'palantir',
  Saronic = 'saronic',
  Nominal = 'nominal',
  Coinbase = 'coinbase',
  Robinhood = 'robinhood',
  Spotify = 'spotify',
  Xai = 'xai',
  Anthropic = 'anthropic',
  Reddit = 'reddit',
  Cloudflare = 'cloudflare',
  Scaleai = 'scaleai',
  Lyft = 'lyft',
  Doordashusa = 'doordashusa',
  Stripe = 'stripe',
  Ramp = 'ramp',
  Snowflake = 'snowflake',
  Plaid = 'plaid',
  AppliedIntuition = 'appliedintuition',
  Discord = 'discord',
  Brex = 'brex',
  Squarespace = 'Squarespace',
  Nvidia = 'nvidia',
  Adobe = 'adobe',
}

/**
 * Get company configuration by ID
 */
export function getCompanyById(id: string): Company | undefined {
  return COMPANIES.find((c) => c.id === id);
}
