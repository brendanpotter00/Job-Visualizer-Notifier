import type {
  BackendScraperConfig,
  Company,
  GemConfig,
  LeverConfig,
  WorkdayConfig,
} from '../types';

/**
 * Options for factory functions
 */
interface FactoryOptions {
  recruiterLinkedInUrl?: string;
}

interface WorkdayOptions extends FactoryOptions {
  defaultFacets?: Record<string, string[]>;
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
  options: FactoryOptions & { sourceAts?: 'ashby' | 'greenhouse' | 'eightfold' } = {}
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
    sourceAts: options.sourceAts,
    recruiterLinkedInUrl: options.recruiterLinkedInUrl,
  };
}

/**
 * Company configurations for multi-ATS support
 */

export const COMPANIES: Company[] = [
  // Backend scraper companies (formerly Greenhouse)
  createBackendScraperCompany('spacex', 'SpaceX', 'https://boards.greenhouse.io/spacex', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2230846%22%5D',
  }),
  createBackendScraperCompany('andurilindustries', 'Anduril', 'https://boards.greenhouse.io/andurilindustries', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218293159%22%5D',
  }),
  createBackendScraperCompany('airtable', 'Airtable', 'https://boards.greenhouse.io/airtable', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('airbnb', 'Airbnb', 'https://boards.greenhouse.io/airbnb', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22309694%22%5D',
  }),
  createBackendScraperCompany('fireworksai', 'Fireworks AI', 'https://boards.greenhouse.io/fireworksai', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('figma', 'Figma', 'https://boards.greenhouse.io/figma', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223650502%22%5D',
  }),
  createBackendScraperCompany('twitch', 'Twitch', 'https://boards.greenhouse.io/twitch', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222320329%22%5D',
  }),
  createBackendScraperCompany('neuralink', 'Neuralink', 'https://boards.greenhouse.io/neuralink', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2219002862%22%5D',
  }),
  createBackendScraperCompany('robinhood', 'Robinhood', 'https://boards.greenhouse.io/robinhood', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createBackendScraperCompany('xai', 'XAI', 'https://boards.greenhouse.io/xai', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2296151950%22%5D',
  }),
  createBackendScraperCompany('anthropic', 'Anthropic', 'https://boards.greenhouse.io/anthropic', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2274126343%22%5D',
  }),
  createBackendScraperCompany('reddit', 'Reddit', 'https://boards.greenhouse.io/reddit', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22150573%22%5D',
  }),
  createBackendScraperCompany('cloudflare', 'Cloudflare', 'https://boards.greenhouse.io/cloudflare', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('scaleai', 'ScaleAI', 'https://boards.greenhouse.io/scaleai', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('lyft', 'Lyft', 'https://boards.greenhouse.io/lyft', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222620735%22%5D',
  }),
  createBackendScraperCompany('doordashusa', 'Doordash', 'https://boards.greenhouse.io/doordashusa', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223205573%22%5D',
  }),
  createBackendScraperCompany('stripe', 'Stripe', 'https://boards.greenhouse.io/stripe', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222135371%22%5D',
  }),
  createBackendScraperCompany('appliedintuition', 'Applied Intuition', 'https://boards.greenhouse.io/appliedintuition', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createBackendScraperCompany('discord', 'Discord', 'https://boards.greenhouse.io/discord', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223765675%22%5D',
  }),
  createBackendScraperCompany('brex', 'Brex', 'https://boards.greenhouse.io/brex', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218505670%22%5D',
  }),
  createBackendScraperCompany('squarespace', 'Squarespace', 'https://boards.greenhouse.io/squarespace', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createBackendScraperCompany('clear', 'Clear', 'https://boards.greenhouse.io/clear', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('affirm', 'Affirm', 'https://boards.greenhouse.io/affirm', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('crunchyroll', 'Crunchyroll', 'https://boards.greenhouse.io/crunchyroll', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('nuro', 'Nuro', 'https://boards.greenhouse.io/nuro', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('pallet', 'Pallet', 'https://boards.greenhouse.io/pallet', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('pinterest', 'Pinterest', 'https://boards.greenhouse.io/pinterest', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221124131%22%5D',
  }),
  createBackendScraperCompany('astranis', 'Astranis', 'https://boards.greenhouse.io/astranis', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('chalk', 'Chalk', 'https://careers.ashbyhq.com/chalk', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2278829224%22%5D',
  }),
  createBackendScraperCompany('waymo', 'Waymo', 'https://boards.greenhouse.io/waymo', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2217900793%22%5D',
  }),
  createBackendScraperCompany('figureai', 'Figure AI', 'https://boards.greenhouse.io/figureai', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2285645770%22%5D',
  }),
  createBackendScraperCompany('gleanwork', 'Glean', 'https://boards.greenhouse.io/gleanwork', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('merge', 'Merge', 'https://boards.greenhouse.io/merge', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('databricks', 'Databricks', 'https://boards.greenhouse.io/databricks', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('datadog', 'Datadog', 'https://boards.greenhouse.io/datadog', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('dropbox', 'Dropbox', 'https://boards.greenhouse.io/dropbox', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('instacart', 'Instacart', 'https://boards.greenhouse.io/instacart', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('mongodb', 'MongoDB', 'https://boards.greenhouse.io/mongodb', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('twilio', 'Twilio', 'https://boards.greenhouse.io/twilio', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('block', 'Block', 'https://boards.greenhouse.io/block', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('gitlab', 'GitLab', 'https://boards.greenhouse.io/gitlab', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('unity3d', 'Unity', 'https://boards.greenhouse.io/unity3d', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('vercel', 'Vercel', 'https://boards.greenhouse.io/vercel', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('thinkingmachines', 'Thinking Machines', 'https://boards.greenhouse.io/thinkingmachines', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('togetherai', 'Together AI', 'https://boards.greenhouse.io/togetherai', {
    sourceAts: 'greenhouse',
  }),
  createBackendScraperCompany('hightouch', 'Hightouch', 'https://boards.greenhouse.io/hightouch', {
    sourceAts: 'greenhouse',
  }),

  // Lever companies
  createLeverCompany('palantir', 'Palantir', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2220708%22%5D',
  }),
  createLeverCompany('spotify', 'Spotify', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22207470%22%5D',
  }),
  createLeverCompany('zoox', 'Zoox', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  // Ashby companies (migrated to backend-scraper)
  createBackendScraperCompany('notion', 'Notion', 'https://careers.ashbyhq.com/notion', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2230898036%22%5D',
  }),
  createBackendScraperCompany('ramp', 'Ramp', 'https://careers.ashbyhq.com/ramp', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221406226%22%5D',
  }),
  createBackendScraperCompany('snowflake', 'Snowflake', 'https://careers.ashbyhq.com/snowflake', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223653845%22%5D',
  }),
  createBackendScraperCompany('decagon', 'Decagon', 'https://careers.ashbyhq.com/decagon', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('distyl', 'Distyl', 'https://careers.ashbyhq.com/Distyl', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('elevenlabs', 'ElevenLabs', 'https://careers.ashbyhq.com/elevenlabs', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2286583130%22%5D',
  }),
  createBackendScraperCompany('flowengineering', 'Flow Engineering', 'https://careers.ashbyhq.com/flowengineering', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218030570%22%5D',
  }),
  createBackendScraperCompany('baseten', 'Baseten', 'https://careers.ashbyhq.com/baseten', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('browserbase', 'Browserbase', 'https://careers.ashbyhq.com/browserbase', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22100530625%22%5D',
  }),
  createBackendScraperCompany('base-power', 'Base Power Company', 'https://careers.ashbyhq.com/base-power', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  createBackendScraperCompany('clickup', 'ClickUp', 'https://careers.ashbyhq.com/clickup', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('apex-technology-inc', 'Apex Technology Inc', 'https://careers.ashbyhq.com/apex-technology-inc', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('light', 'Light', 'https://careers.ashbyhq.com/light', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('linear', 'Linear', 'https://careers.ashbyhq.com/Linear', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2229309454%22%5D',
  }),
  createBackendScraperCompany('siftstack', 'Sift Stack', 'https://careers.ashbyhq.com/siftstack', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2297188584%22%5D',
  }),
  createBackendScraperCompany('stainlessapi', 'Stainless API', 'https://careers.ashbyhq.com/stainlessapi', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('gigaml', 'GigaML', 'https://careers.ashbyhq.com/GigaML', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2287441542%22%5D',
  }),
  createBackendScraperCompany('sesame', 'Sesame', 'https://careers.ashbyhq.com/sesame', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22105311076%22%5D',
  }),
  createBackendScraperCompany('happyrobot.ai', 'Happyrobot', 'https://careers.ashbyhq.com/happyrobot.ai', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('granola', 'Granola', 'https://careers.ashbyhq.com/granola', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('sunday', 'Sunday', 'https://careers.ashbyhq.com/sunday', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('openai', 'OpenAI', 'https://careers.ashbyhq.com/openai', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('perplexity', 'Perplexity', 'https://careers.ashbyhq.com/perplexity', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('pylon-labs', 'Pylon', 'https://careers.ashbyhq.com/pylon-labs', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('cohere', 'Cohere', 'https://careers.ashbyhq.com/cohere', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('traversal', 'Traversal', 'https://careers.ashbyhq.com/traversal', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('harvey', 'Harvey', 'https://careers.ashbyhq.com/harvey', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('sentry', 'Sentry', 'https://careers.ashbyhq.com/sentry', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('braintrust', 'Braintrust', 'https://careers.ashbyhq.com/Braintrust', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('eliseai', 'EliseAI', 'https://careers.ashbyhq.com/eliseai', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('resolve-ai', 'Resolve AI', 'https://careers.ashbyhq.com/Resolve AI', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('mintlify', 'Mintlify', 'https://careers.ashbyhq.com/Mintlify', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('roadrunner', 'Roadrunner', 'https://careers.ashbyhq.com/Roadrunner', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('supabase', 'Supabase', 'https://careers.ashbyhq.com/supabase', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('wispr-flow', 'Wispr Flow', 'https://careers.ashbyhq.com/wispr-flow', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('flint', 'Flint', 'https://careers.ashbyhq.com/flint', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('cursor', 'Cursor', 'https://cursor.com/careers', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('modal', 'Modal Labs', 'https://careers.ashbyhq.com/modal', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('langchain', 'LangChain', 'https://careers.ashbyhq.com/langchain', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('cognition', 'Cognition', 'https://careers.ashbyhq.com/cognition', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('paraform', 'Paraform', 'https://careers.ashbyhq.com/paraform', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('judgmentlabs', 'Judgment Labs', 'https://careers.ashbyhq.com/judgmentlabs', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('generalintelligencecompany', 'General Intelligence Company', 'https://careers.ashbyhq.com/generalintelligencecompany', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('saronic', 'Saronic', 'https://jobs.ashbyhq.com/saronic', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2289680213%22%5D',
  }),
  createBackendScraperCompany('plaid', 'Plaid', 'https://jobs.ashbyhq.com/plaid', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222684737%22%5D',
  }),

  // Gem companies
  createGemCompany('nominal', 'Nominal'),
  createGemCompany('retool', 'Retool'),
  createGemCompany('gem', 'Gem'),

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
  createWorkdayCompany('paypal', 'PayPal', {
    baseUrl: 'https://paypal.wd1.myworkdayjobs.com',
    tenantSlug: 'paypal',
    careerSiteSlug: 'jobs',
  }),

  // Backend scraper companies (formerly Eightfold)
  createBackendScraperCompany('netflix', 'Netflix', 'https://explore.jobs.netflix.net/', {
    sourceAts: 'eightfold',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22165158%22%5D',
  }),

  // Backend scraper companies (Python-scraped: Google, Apple, Microsoft)
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
  Airtable = 'airtable',
  AndurilIndustries = 'andurilindustries',
  Anthropic = 'anthropic',
  ApexTechnologyInc = 'apex-technology-inc',
  Apple = 'apple',
  AppliedIntuition = 'appliedintuition',
  Astranis = 'astranis',
  Baseten = 'baseten',
  BasePower = 'base-power',
  Block = 'block',
  BlueOrigin = 'blueorigin',
  Brex = 'brex',
  Braintrust = 'braintrust',
  Browserbase = 'browserbase',
  CapitalOne = 'capitalone',
  Chalk = 'chalk',
  Clear = 'clear',
  ClickUp = 'clickup',
  Cloudflare = 'cloudflare',
  Cognition = 'cognition',
  Cohere = 'cohere',
  Crunchyroll = 'crunchyroll',
  Cursor = 'cursor',
  Databricks = 'databricks',
  Decagon = 'decagon',
  Datadog = 'datadog',
  Discord = 'discord',
  Distyl = 'distyl',
  Dropbox = 'dropbox',
  Disney = 'disney',
  Doordashusa = 'doordashusa',
  ElevenLabs = 'elevenlabs',
  EliseAI = 'eliseai',
  Expedia = 'expedia',
  Figma = 'figma',
  FigureAI = 'figureai',
  Flint = 'flint',
  FireworksAI = 'fireworksai',
  FlowEngineering = 'flowengineering',
  GeneralIntelligenceCompany = 'generalintelligencecompany',
  GeneralMotors = 'gm',
  GigaML = 'gigaml',
  GitLab = 'gitlab',
  Glean = 'gleanwork',
  Google = 'google',
  Granola = 'granola',
  Harvey = 'harvey',
  Happyrobot = 'happyrobot.ai',
  Hightouch = 'hightouch',
  Instacart = 'instacart',
  JudgmentLabs = 'judgmentlabs',
  LangChain = 'langchain',
  Light = 'light',
  Linear = 'linear',
  Lyft = 'lyft',
  Merge = 'merge',
  Microsoft = 'microsoft',
  Mintlify = 'mintlify',
  ModalLabs = 'modal',
  MongoDB = 'mongodb',
  Netflix = 'netflix',
  Neuralink = 'neuralink',
  Nominal = 'nominal',
  Notion = 'notion',
  Nuro = 'nuro',
  Nvidia = 'nvidia',
  OpenAI = 'openai',
  Pallet = 'pallet',
  Palantir = 'palantir',
  Paraform = 'paraform',
  PayPal = 'paypal',
  Perplexity = 'perplexity',
  Pylon = 'pylon-labs',
  Pinterest = 'pinterest',
  Plaid = 'plaid',
  Ramp = 'ramp',
  Reddit = 'reddit',
  ResolveAI = 'resolve-ai',
  Roadrunner = 'roadrunner',
  Robinhood = 'robinhood',
  Saronic = 'saronic',
  Scaleai = 'scaleai',
  Sesame = 'sesame',
  Sentry = 'sentry',
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
  Supabase = 'supabase',
  ThinkingMachines = 'thinkingmachines',
  TogetherAI = 'togetherai',
  Traversal = 'traversal',
  Twilio = 'twilio',
  Turo = 'turo',
  Twitch = 'twitch',
  Unity = 'unity3d',
  Vercel = 'vercel',
  Waymo = 'waymo',
  WisprFlow = 'wispr-flow',
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
