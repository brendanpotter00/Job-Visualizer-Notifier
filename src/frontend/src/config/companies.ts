import type {
  AshbyConfig,
  BackendScraperConfig,
  Company,
  GreenhouseConfig,
  LeverConfig,
  WorkdayConfig,
} from '../types';

/**
 * Options for factory functions
 */
interface FactoryOptions {
  recruiterLinkedInUrl?: string;
}

interface GreenhouseOptions extends FactoryOptions {
  boardToken?: string;
}

interface WorkdayOptions extends FactoryOptions {
  defaultFacets?: Record<string, string[]>;
}

/**
 * Factory function for Greenhouse companies.
 * Defaults boardToken to the company id.
 */
function createGreenhouseCompany(
  id: string,
  name: string,
  options: GreenhouseOptions = {}
): Company {
  const boardToken = options.boardToken ?? id;
  const config: GreenhouseConfig = {
    type: 'greenhouse',
    boardToken,
  };
  return {
    id,
    name,
    ats: 'greenhouse',
    config,
    jobsUrl: `https://boards.greenhouse.io/${boardToken}`,
    recruiterLinkedInUrl: options.recruiterLinkedInUrl,
  };
}

/**
 * Factory function for Lever companies.
 * Computes jobsUrl from company id.
 */
function createLeverCompany(
  id: string,
  name: string,
  options: FactoryOptions = {}
): Company {
  const jobsUrl = `https://jobs.lever.co/${id}`;
  const config: LeverConfig = {
    type: 'lever',
    companyId: id,
    jobsUrl,
  };
  return {
    id,
    name,
    ats: 'lever',
    config,
    jobsUrl,
    recruiterLinkedInUrl: options.recruiterLinkedInUrl,
  };
}

/**
 * Factory function for Ashby companies.
 * Defaults jobBoardName to the company id.
 */
function createAshbyCompany(
  id: string,
  name: string,
  options: FactoryOptions = {}
): Company {
  const config: AshbyConfig = {
    type: 'ashby',
    jobBoardName: id,
  };
  return {
    id,
    name,
    ats: 'ashby',
    config,
    jobsUrl: `https://careers.ashbyhq.com/${id}`,
    recruiterLinkedInUrl: options.recruiterLinkedInUrl,
  };
}

/**
 * Factory function for Workday companies.
 * Requires explicit configuration for baseUrl, tenantSlug, and careerSiteSlug.
 */
function createWorkdayCompany(
  id: string,
  name: string,
  workdayConfig: {
    baseUrl: string;
    tenantSlug: string;
    careerSiteSlug: string;
  },
  options: WorkdayOptions = {}
): Company {
  const jobsUrl = `${workdayConfig.baseUrl}/${workdayConfig.careerSiteSlug}/details`;
  const config: WorkdayConfig = {
    type: 'workday',
    baseUrl: workdayConfig.baseUrl,
    tenantSlug: workdayConfig.tenantSlug,
    careerSiteSlug: workdayConfig.careerSiteSlug,
    jobsUrl,
    defaultFacets: options.defaultFacets,
  };
  return {
    id,
    name,
    ats: 'workday',
    config,
    jobsUrl,
    recruiterLinkedInUrl: options.recruiterLinkedInUrl,
  };
}

/**
 * Factory function for backend-scraper companies.
 * These are companies scraped via Python scripts and served from our backend.
 */
function createBackendScraperCompany(
  id: string,
  name: string,
  jobsUrl: string,
  options: FactoryOptions = {}
): Company {
  const config: BackendScraperConfig = {
    type: 'backend-scraper',
    companyId: id,
    apiBaseUrl: '/api/jobs',
  };
  return {
    id,
    name,
    ats: 'backend-scraper',
    config,
    jobsUrl,
    recruiterLinkedInUrl: options.recruiterLinkedInUrl,
  };
}

/**
 * Company configurations for multi-ATS support
 */
export const COMPANIES: Company[] = [
  // Greenhouse companies
  createGreenhouseCompany('spacex', 'SpaceX', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2230846%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=Gp2&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('andurilindustries', 'Anduril', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2218293159%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=vst&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('airbnb', 'Airbnb', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%22309694%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=Am6&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('figma', 'Figma', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223650502%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=Hnn&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('twitch', 'Twitch', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%222320329%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=W!P&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('neuralink', 'Neuralink', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2219002862%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=6Ij&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('coinbase', 'Coinbase', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%222857634%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=65F&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('robinhood', 'Robinhood', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223254263%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=AsA&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('xai', 'XAI', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2296151950%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=bYM&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('anthropic', 'Anthropic', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2274126343%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=L2U&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('reddit', 'Reddit', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%22150573%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=4ar&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('cloudflare', 'Cloudflare'),
  createGreenhouseCompany('scaleai', 'ScaleAI'),
  createGreenhouseCompany('lyft', 'Lyft', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%222620735%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=hp!&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('doordashusa', 'Doordash', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223205573%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=DT%3A&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('stripe', 'Stripe', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%222135371%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=z(2&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('appliedintuition', 'Applied Intuition', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2218808325%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=Pz-&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('discord', 'Discord', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223765675%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=P0b&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('brex', 'Brex', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2218505670%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=o-E&sortBy=%22date_posted%22',
  }),
  createGreenhouseCompany('squarespace', 'Squarespace', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%22265314%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=JwA&sortBy=%22date_posted%22',
  }),

  // Lever companies
  createLeverCompany('palantir', 'Palantir', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2220708%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=%40ld&sortBy=%22date_posted%22',
  }),
  createLeverCompany('saronic', 'Saronic', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2289680213%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=aOp&sortBy=%22date_posted%22',
  }),
  createLeverCompany('nominal', 'Nominal', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2292924343%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=a5Q&sortBy=%22date_posted%22',
  }),
  createLeverCompany('spotify', 'Spotify', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%22207470%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=%4072&sortBy=%22date_posted%22',
  }),
  createLeverCompany('plaid', 'Plaid', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%222684737%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=8n%3B&sortBy=%22date_posted%22',
  }),

  // Ashby companies
  createAshbyCompany('notion', 'Notion', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%2230898036%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=_GL&sortBy=%22date_posted%22',
  }),
  createAshbyCompany('ramp', 'Ramp', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%221406226%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=e%3Ab&sortBy=%22date_posted%22',
  }),
  createAshbyCompany('snowflake', 'Snowflake', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223653845%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=4o9&sortBy=%22date_posted%22',
  }),
  createAshbyCompany('elevenlabs', 'ElevenLabs'),

  // Workday companies
  createWorkdayCompany(
    'nvidia',
    'NVIDIA',
    {
      baseUrl: 'https://nvidia.wd5.myworkdayjobs.com',
      tenantSlug: 'nvidia',
      careerSiteSlug: 'NVIDIAExternalCareerSite',
    },
    {
      defaultFacets: {
        locationHierarchy1: ['2fcb99c455831013ea52fb338f2932d8'], // United States
        jobFamilyGroup: ['0c40f6bd1d8f10ae43ffaefd46dc7e78'], // Engineering
        timeType: ['5509c0b5959810ac0029943377d47364'], // Full time
      },
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?authorCompany=%5B%223608%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=YU9&sortBy=%22date_posted%22',
    }
  ),
  createWorkdayCompany(
    'adobe',
    'Adobe',
    {
      baseUrl: 'https://adobe.wd5.myworkdayjobs.com',
      tenantSlug: 'adobe',
      careerSiteSlug: 'external_experienced',
    },
    {
      defaultFacets: {
        locationCountry: ['bc33aa3152ec42d4995f4791a106ed09'], // United States
        jobFamilyGroup: [
          '591af8b812fa10737af39db3d96eed9f',
          '591af8b812fa10737b43a1662896f01c',
        ], // Engineering, University
      },
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?authorCompany=%5B%221480%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sid=!%3BQ&sortBy=%22date_posted%22',
    }
  ),

  // Backend scraper companies
  createBackendScraperCompany('google', 'Google', 'https://careers.google.com/', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%221441%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%22date_posted%22',
  }),
  createBackendScraperCompany('apple', 'Apple', 'https://jobs.apple.com/', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?authorCompany=%5B%22162479%22%5D&keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%22date_posted%22',
  }),
];

export const enum COMPANY_IDS {
  Spacex = 'spacex',
  AndurilIndustries = 'andurilindustries',
  Airbnb = 'airbnb',
  Figma = 'figma',
  Notion = 'notion',
  Twitch = 'twitch',
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
  Squarespace = 'squarespace',
  Nvidia = 'nvidia',
  Adobe = 'adobe',
  ElevenLabs = 'elevenlabs',
  Google = 'google',
  Apple = 'apple',
}

/**
 * Get company configuration by ID
 */
export function getCompanyById(id: string): Company | undefined {
  return COMPANIES.find((c) => c.id === id);
}

/**
 * Coming soon companies for custom scrapers section
 */
export const COMING_SOON_SCRAPERS = [
  { name: 'Netflix', jobsUrl: 'https://jobs.netflix.com/' },
] as const;
