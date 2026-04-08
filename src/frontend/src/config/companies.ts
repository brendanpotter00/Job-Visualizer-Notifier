import type {
  AshbyConfig,
  BackendScraperConfig,
  Company,
  GemConfig,
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

interface AshbyOptions extends FactoryOptions {
  jobBoardName?: string;
}

interface GemOptions extends FactoryOptions {
  vanityUrlPath?: string;
}

/**
 * Factory function for Gem companies.
 * Defaults vanityUrlPath to the company id.
 */
function createGemCompany(
  id: string,
  name: string,
  options: GemOptions = {}
): Company {
  const vanityUrlPath = options.vanityUrlPath ?? id;
  const config: GemConfig = {
    type: 'gem',
    vanityUrlPath,
  };
  return {
    id,
    name,
    ats: 'gem',
    config,
    jobsUrl: `https://jobs.gem.com/${vanityUrlPath}`,
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
  options: AshbyOptions = {}
): Company {
  const jobBoardName = options.jobBoardName ?? id;
  const config: AshbyConfig = {
    type: 'ashby',
    jobBoardName,
  };
  return {
    id,
    name,
    ats: 'ashby',
    config,
    jobsUrl: `https://careers.ashbyhq.com/${jobBoardName}`,
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
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2230846%22%5D',
  }),
  createGreenhouseCompany('andurilindustries', 'Anduril', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218293159%22%5D',
  }),
  createGreenhouseCompany('airbnb', 'Airbnb', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22309694%22%5D',
  }),
  createGreenhouseCompany('figma', 'Figma', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223650502%22%5D',
  }),
  createGreenhouseCompany('twitch', 'Twitch', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222320329%22%5D',
  }),
  createGreenhouseCompany('neuralink', 'Neuralink', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2219002862%22%5D',
  }),
  createGreenhouseCompany('coinbase', 'Coinbase', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222857634%22%5D',
  }),
  createGreenhouseCompany('robinhood', 'Robinhood', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createGreenhouseCompany('xai', 'XAI', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2296151950%22%5D',
  }),
  createGreenhouseCompany('anthropic', 'Anthropic', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2274126343%22%5D',
  }),
  createGreenhouseCompany('reddit', 'Reddit', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22150573%22%5D',
  }),
  createGreenhouseCompany('cloudflare', 'Cloudflare'),
  createGreenhouseCompany('scaleai', 'ScaleAI'),
  createGreenhouseCompany('lyft', 'Lyft', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222620735%22%5D',
  }),
  createGreenhouseCompany('doordashusa', 'Doordash', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223205573%22%5D',
  }),
  createGreenhouseCompany('stripe', 'Stripe', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222135371%22%5D',
  }),
  createGreenhouseCompany('appliedintuition', 'Applied Intuition', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createGreenhouseCompany('discord', 'Discord', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223765675%22%5D',
  }),
  createGreenhouseCompany('brex', 'Brex', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218505670%22%5D',
  }),
  createGreenhouseCompany('squarespace', 'Squarespace', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createGreenhouseCompany('clear', 'Clear'),
  createGreenhouseCompany('affirm', 'Affirm'),
  createGreenhouseCompany('crunchyroll', 'Crunchyroll'),
  createGreenhouseCompany('nuro', 'Nuro'),
  createGreenhouseCompany('trueanomalyinc', 'True Anomaly'),
  createGreenhouseCompany('pinterest', 'Pinterest', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221124131%22%5D',
  }),
  createGreenhouseCompany('astranis', 'Astranis'),
  createGreenhouseCompany('chalkinc', 'Chalk', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2278829224%22%5D',
  }),
  createGreenhouseCompany('waymo', 'Waymo', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2217900793%22%5D',
  }),
  createGreenhouseCompany('figureai', 'Figure AI', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2285645770%22%5D',
  }),
  createGreenhouseCompany('gleanwork', 'Glean'),
  createGreenhouseCompany('merge', 'Merge'),
  createGreenhouseCompany('databricks', 'Databricks'),
  createGreenhouseCompany('datadog', 'Datadog'),
  createGreenhouseCompany('dropbox', 'Dropbox'),
  createGreenhouseCompany('instacart', 'Instacart'),
  createGreenhouseCompany('mongodb', 'MongoDB'),
  createGreenhouseCompany('twilio', 'Twilio'),
  createGreenhouseCompany('block', 'Block'),
  createGreenhouseCompany('gitlab', 'GitLab'),
  createGreenhouseCompany('unity3d', 'Unity'),
  createGreenhouseCompany('cruise', 'Cruise'),
  createGreenhouseCompany('rippling', 'Rippling'),

  // Lever companies
  createLeverCompany('palantir', 'Palantir', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2220708%22%5D',
  }),
  createLeverCompany('saronic', 'Saronic', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2289680213%22%5D',
  }),
  createLeverCompany('spotify', 'Spotify', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22207470%22%5D',
  }),
  createLeverCompany('plaid', 'Plaid', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222684737%22%5D',
  }),
  createLeverCompany('zoox', 'Zoox', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createLeverCompany('netlify', 'Netlify'),

  // Ashby companies
  createAshbyCompany('notion', 'Notion', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2230898036%22%5D',
  }),
  createAshbyCompany('ramp', 'Ramp', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221406226%22%5D',
  }),
  createAshbyCompany('snowflake', 'Snowflake', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223653845%22%5D',
  }),
  createAshbyCompany('elevenlabs', 'ElevenLabs', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2286583130%22%5D',
  }),
  createAshbyCompany('flowengineering', 'Flow Engineering', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218030570%22%5D',
  }),
  createAshbyCompany('browserbase', 'Browserbase', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22100530625%22%5D',
  }),
  createAshbyCompany('base-power', 'Base Power Company', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createAshbyCompany('clickup', 'ClickUp'),
  createAshbyCompany('apex-technology-inc', 'Apex Technology Inc'),
  createAshbyCompany('light', 'Light'),
  createAshbyCompany('linear', 'Linear', {
    jobBoardName: 'Linear',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2229309454%22%5D',
  }),
  createAshbyCompany('siftstack', 'Sift Stack', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2297188584%22%5D',
  }),
  createAshbyCompany('stainlessapi', 'Stainless API'),
  createAshbyCompany('gigaml', 'GigaML', {
    jobBoardName: 'GigaML',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2287441542%22%5D',
  }),
  createAshbyCompany('sesame', 'Sesame', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22105311076%22%5D',
  }),
  createAshbyCompany('happyrobot.ai', 'Happyrobot', { jobBoardName: 'happyrobot.ai' }),
  createAshbyCompany('granola', 'Granola'),
  createAshbyCompany('sunday', 'Sunday'),
  createAshbyCompany('openai', 'OpenAI'),
  createAshbyCompany('vercel', 'Vercel'),
  createAshbyCompany('perplexity', 'Perplexity'),
  createAshbyCompany('cohere', 'Cohere'),
  createAshbyCompany('mistralai', 'Mistral'),

  // Gem companies
  createGemCompany('nominal', 'Nominal'),

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
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223608%22%5D',
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
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221480%22%5D',
    }
  ),
  createWorkdayCompany('expedia', 'Expedia', {
    baseUrl: 'https://expedia.wd108.myworkdayjobs.com',
    tenantSlug: 'expedia',
    careerSiteSlug: 'search',
  }),
  createWorkdayCompany(
    'netflix',
    'Netflix',
    {
      baseUrl: 'https://netflix.wd1.myworkdayjobs.com',
      tenantSlug: 'netflix',
      careerSiteSlug: 'Netflix',
    },
    {
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22165158%22%5D',
    }
  ),
  createWorkdayCompany('turo', 'Turo', {
    baseUrl: 'https://turo.wd12.myworkdayjobs.com',
    tenantSlug: 'turo',
    careerSiteSlug: 'Turo_careers',
  }),
  createWorkdayCompany('blueorigin', 'Blue Origin', {
    baseUrl: 'https://blueorigin.wd5.myworkdayjobs.com',
    tenantSlug: 'blueorigin',
    careerSiteSlug: 'BlueOrigin',
  }),
  createWorkdayCompany('snap', 'Snap', {
    baseUrl: 'https://snapchat.wd1.myworkdayjobs.com',
    tenantSlug: 'snapchat',
    careerSiteSlug: 'snap',
  }),
  createWorkdayCompany('gm', 'General Motors', {
    baseUrl: 'https://generalmotors.wd5.myworkdayjobs.com',
    tenantSlug: 'generalmotors',
    careerSiteSlug: 'Careers_GM',
  }),
  createWorkdayCompany('disney', 'Disney', {
    baseUrl: 'https://disney.wd5.myworkdayjobs.com',
    tenantSlug: 'disney',
    careerSiteSlug: 'disneycareer',
  }),
  createWorkdayCompany('slack', 'Slack', {
    baseUrl: 'https://salesforce.wd12.myworkdayjobs.com',
    tenantSlug: 'salesforce',
    careerSiteSlug: 'Slack',
  }),
  createWorkdayCompany('capitalone', 'Capital One', {
    baseUrl: 'https://capitalone.wd12.myworkdayjobs.com',
    tenantSlug: 'capitalone',
    careerSiteSlug: 'Capital_One',
  }),

  // Backend scraper companies
  createBackendScraperCompany('google', 'Google', 'https://careers.google.com/', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createBackendScraperCompany('apple', 'Apple', 'https://jobs.apple.com/', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22162479%22%5D',
  }),
  createBackendScraperCompany('microsoft', 'Microsoft', 'https://careers.microsoft.com/', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221035%22%5D',
  }),
];

export const enum COMPANY_IDS {
  Adobe = 'adobe',
  Affirm = 'affirm',
  Airbnb = 'airbnb',
  AndurilIndustries = 'andurilindustries',
  Anthropic = 'anthropic',
  ApexTechnologyInc = 'apex-technology-inc',
  Apple = 'apple',
  AppliedIntuition = 'appliedintuition',
  Astranis = 'astranis',
  BasePower = 'base-power',
  Block = 'block',
  BlueOrigin = 'blueorigin',
  Brex = 'brex',
  Browserbase = 'browserbase',
  CapitalOne = 'capitalone',
  Chalk = 'chalkinc',
  Clear = 'clear',
  ClickUp = 'clickup',
  Cloudflare = 'cloudflare',
  Cohere = 'cohere',
  Coinbase = 'coinbase',
  Cruise = 'cruise',
  Crunchyroll = 'crunchyroll',
  Databricks = 'databricks',
  Datadog = 'datadog',
  Discord = 'discord',
  Dropbox = 'dropbox',
  Disney = 'disney',
  Doordashusa = 'doordashusa',
  ElevenLabs = 'elevenlabs',
  Expedia = 'expedia',
  Figma = 'figma',
  FigureAI = 'figureai',
  FlowEngineering = 'flowengineering',
  GeneralMotors = 'gm',
  GigaML = 'gigaml',
  GitLab = 'gitlab',
  Glean = 'gleanwork',
  Google = 'google',
  Granola = 'granola',
  Happyrobot = 'happyrobot.ai',
  Instacart = 'instacart',
  Light = 'light',
  Linear = 'linear',
  Lyft = 'lyft',
  Mistral = 'mistralai',
  Merge = 'merge',
  Microsoft = 'microsoft',
  MongoDB = 'mongodb',
  Netflix = 'netflix',
  Netlify = 'netlify',
  Neuralink = 'neuralink',
  Nominal = 'nominal',
  Notion = 'notion',
  Nuro = 'nuro',
  Nvidia = 'nvidia',
  OpenAI = 'openai',
  Palantir = 'palantir',
  Perplexity = 'perplexity',
  Pinterest = 'pinterest',
  Plaid = 'plaid',
  Ramp = 'ramp',
  Reddit = 'reddit',
  Rippling = 'rippling',
  Robinhood = 'robinhood',
  Saronic = 'saronic',
  Scaleai = 'scaleai',
  Sesame = 'sesame',
  SiftStack = 'siftstack',
  Slack = 'slack',
  Snap = 'snap',
  Snowflake = 'snowflake',
  Spacex = 'spacex',
  Spotify = 'spotify',
  Squarespace = 'squarespace',
  StainlessApi = 'stainlessapi',
  Stripe = 'stripe',
  Sunday = 'sunday',
  TrueAnomaly = 'trueanomalyinc',
  Twilio = 'twilio',
  Turo = 'turo',
  Twitch = 'twitch',
  Unity = 'unity3d',
  Vercel = 'vercel',
  Waymo = 'waymo',
  Xai = 'xai',
  Zoox = 'zoox',
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
export const COMING_SOON_SCRAPERS: readonly { name: string; jobsUrl: string }[] = [];
