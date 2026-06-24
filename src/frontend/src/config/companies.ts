import type { BackendScraperConfig, Company } from '../types';

/**
 * Options for factory functions
 */
interface FactoryOptions {
  recruiterLinkedInUrl?: string;
}

/**
 * Factory function for backend-scraper companies.
 * These are companies scraped via Python scripts and served from our backend.
 */
function createBackendScraperCompany(
  id: string,
  name: string,
  jobsUrl: string,
  options: FactoryOptions & {
    sourceAts?:
      | 'ashby'
      | 'eightfold'
      | 'gem'
      | 'greenhouse'
      | 'lever'
      | 'workday';
  } = {}
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223991822%22%5D',
  }),
  createBackendScraperCompany('airbnb', 'Airbnb', 'https://boards.greenhouse.io/airbnb', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22309694%22%5D',
  }),
  createBackendScraperCompany('fireworksai', 'Fireworks AI', 'https://boards.greenhouse.io/fireworksai', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2291174981%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22407222%22%5D',
  }),
  createBackendScraperCompany('scaleai', 'ScaleAI', 'https://boards.greenhouse.io/scaleai', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2217998520%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22961661%22%5D',
  }),
  createBackendScraperCompany('affirm', 'Affirm', 'https://boards.greenhouse.io/affirm', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222963249%22%5D',
  }),
  createBackendScraperCompany('crunchyroll', 'Crunchyroll', 'https://boards.greenhouse.io/crunchyroll', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22167212%22%5D',
  }),
  createBackendScraperCompany('nuro', 'Nuro', 'https://boards.greenhouse.io/nuro', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2212957486%22%5D',
  }),
  createBackendScraperCompany('pallet', 'Pallet', 'https://boards.greenhouse.io/pallet', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2291161815%22%5D',
  }),
  createBackendScraperCompany('pinterest', 'Pinterest', 'https://boards.greenhouse.io/pinterest', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221124131%22%5D',
  }),
  createBackendScraperCompany('astranis', 'Astranis', 'https://boards.greenhouse.io/astranis', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2210891165%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2274882602%22%5D',
  }),
  createBackendScraperCompany('merge', 'Merge', 'https://boards.greenhouse.io/merge', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2253197721%22%5D',
  }),
  createBackendScraperCompany('databricks', 'Databricks', 'https://boards.greenhouse.io/databricks', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223477522%22%5D',
  }),
  createBackendScraperCompany('datadog', 'Datadog', 'https://boards.greenhouse.io/datadog', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221066442%22%5D',
  }),
  createBackendScraperCompany('dropbox', 'Dropbox', 'https://boards.greenhouse.io/dropbox', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22167251%22%5D',
  }),
  createBackendScraperCompany('instacart', 'Instacart', 'https://boards.greenhouse.io/instacart', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222732417%22%5D',
  }),
  createBackendScraperCompany('mongodb', 'MongoDB', 'https://boards.greenhouse.io/mongodb', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22783611%22%5D',
  }),
  createBackendScraperCompany('twilio', 'Twilio', 'https://boards.greenhouse.io/twilio', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22400528%22%5D',
  }),
  createBackendScraperCompany('block', 'Block', 'https://boards.greenhouse.io/block', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2280086817%22%5D',
  }),
  createBackendScraperCompany('gitlab', 'GitLab', 'https://boards.greenhouse.io/gitlab', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%225101804%22%5D',
  }),
  createBackendScraperCompany('unity3d', 'Unity', 'https://boards.greenhouse.io/unity3d', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22212669%22%5D',
  }),
  createBackendScraperCompany('vercel', 'Vercel', 'https://boards.greenhouse.io/vercel', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2216181286%22%5D',
  }),
  createBackendScraperCompany('thinkingmachines', 'Thinking Machines', 'https://boards.greenhouse.io/thinkingmachines', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22105913171%22%5D',
  }),
  createBackendScraperCompany('togetherai', 'Together AI', 'https://boards.greenhouse.io/togetherai', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2289816302%22%5D',
  }),
  createBackendScraperCompany('hightouch', 'Hightouch', 'https://boards.greenhouse.io/hightouch', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2242344868%22%5D',
  }),
  createBackendScraperCompany('roblox', 'Roblox', 'https://boards.greenhouse.io/roblox', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22147977%22%5D',
  }),
  createBackendScraperCompany('fal', 'fal', 'https://boards.greenhouse.io/fal', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2277745852%22%5D',
  }),
  // Quant / proprietary trading firms (Greenhouse)
  createBackendScraperCompany('jumptrading', 'Jump Trading', 'https://boards.greenhouse.io/jumptrading', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22294033%22%5D',
  }),
  createBackendScraperCompany('drw', 'DRW', 'https://job-boards.greenhouse.io/drweng', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2215999%22%5D',
  }),
  createBackendScraperCompany('akunacapital', 'Akuna Capital', 'https://job-boards.greenhouse.io/akunacapital', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222322562%22%5D',
  }),
  createBackendScraperCompany('optiver', 'Optiver', 'https://job-boards.greenhouse.io/optiverprivate', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2213216%22%5D',
  }),
  createBackendScraperCompany('imc', 'IMC Trading', 'https://job-boards.greenhouse.io/imc', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22200030%22%5D',
  }),
  createBackendScraperCompany('ctc', 'Chicago Trading (CTC)', 'https://job-boards.greenhouse.io/chicagotrading', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2221004%22%5D',
  }),
  createBackendScraperCompany('hrt', 'Hudson River Trading', 'https://boards.greenhouse.io/wehrtyou', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22730004%22%5D',
  }),

  // Lever companies (migrated to backend-scraper)
  createBackendScraperCompany('palantir', 'Palantir', 'https://jobs.lever.co/palantir', {
    sourceAts: 'lever',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2220708%22%5D',
  }),
  createBackendScraperCompany('spotify', 'Spotify', 'https://jobs.lever.co/spotify', {
    sourceAts: 'lever',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22207470%22%5D',
  }),
  createBackendScraperCompany('zoox', 'Zoox', 'https://jobs.lever.co/zoox', {
    sourceAts: 'lever',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring+software+engineer&origin=FACETED_SEARCH',
  }),
  // Quant / proprietary trading firm (Lever)
  createBackendScraperCompany('belvederetrading', 'Belvedere Trading', 'https://jobs.lever.co/belvederetrading', {
    sourceAts: 'lever',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221266312%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2299221338%22%5D',
  }),
  createBackendScraperCompany('distyl', 'Distyl', 'https://careers.ashbyhq.com/Distyl', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2289943342%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2273802019%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2212949663%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2282462935%22%5D',
  }),
  createBackendScraperCompany('granola', 'Granola', 'https://careers.ashbyhq.com/granola', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('sunday', 'Sunday', 'https://careers.ashbyhq.com/sunday', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22110183058%22%5D',
  }),
  createBackendScraperCompany('openai', 'OpenAI', 'https://careers.ashbyhq.com/openai', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2211130470%22%5D',
  }),
  createBackendScraperCompany('perplexity', 'Perplexity', 'https://careers.ashbyhq.com/perplexity', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2288007673%22%5D',
  }),
  createBackendScraperCompany('pylon-labs', 'Pylon', 'https://careers.ashbyhq.com/pylon-labs', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2289946459%22%5D',
  }),
  createBackendScraperCompany('cohere', 'Cohere', 'https://careers.ashbyhq.com/cohere', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2224024765%22%5D',
  }),
  createBackendScraperCompany('traversal', 'Traversal', 'https://careers.ashbyhq.com/traversal', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22107422026%22%5D',
  }),
  createBackendScraperCompany('harvey', 'Harvey', 'https://careers.ashbyhq.com/harvey', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2289566597%22%5D',
  }),
  createBackendScraperCompany('sentry', 'Sentry', 'https://careers.ashbyhq.com/sentry', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%226424460%22%5D',
  }),
  createBackendScraperCompany('braintrust', 'Braintrust', 'https://careers.ashbyhq.com/Braintrust', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2297196436%22%5D',
  }),
  createBackendScraperCompany('eliseai', 'EliseAI', 'https://careers.ashbyhq.com/eliseai', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2235575530%22%5D',
  }),
  createBackendScraperCompany('resolve-ai', 'Resolve AI', 'https://careers.ashbyhq.com/Resolve AI', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22102498863%22%5D',
  }),
  createBackendScraperCompany('mintlify', 'Mintlify', 'https://careers.ashbyhq.com/Mintlify', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2279912175%22%5D',
  }),
  createBackendScraperCompany('roadrunner', 'Roadrunner', 'https://careers.ashbyhq.com/Roadrunner', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('supabase', 'Supabase', 'https://careers.ashbyhq.com/supabase', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2231546644%22%5D',
  }),
  createBackendScraperCompany('wispr-flow', 'Wispr Flow', 'https://careers.ashbyhq.com/wispr-flow', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2279835899%22%5D',
  }),
  createBackendScraperCompany('flint', 'Flint', 'https://careers.ashbyhq.com/flint', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('cursor', 'Cursor', 'https://cursor.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22105614038%22%5D',
  }),
  createBackendScraperCompany('modal', 'Modal Labs', 'https://careers.ashbyhq.com/modal', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2279045818%22%5D',
  }),
  createBackendScraperCompany('langchain', 'LangChain', 'https://careers.ashbyhq.com/langchain', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2291342320%22%5D',
  }),
  createBackendScraperCompany('cognition', 'Cognition', 'https://careers.ashbyhq.com/cognition', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22101842393%22%5D',
  }),
  createBackendScraperCompany('paraform', 'Paraform', 'https://careers.ashbyhq.com/paraform', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2286609201%22%5D',
  }),
  createBackendScraperCompany('judgmentlabs', 'Judgment Labs', 'https://careers.ashbyhq.com/judgmentlabs', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22106751871%22%5D',
  }),
  createBackendScraperCompany('generalintelligencecompany', 'General Intelligence Company', 'https://careers.ashbyhq.com/generalintelligencecompany', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22106851676%22%5D',
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
  createBackendScraperCompany('exa', 'Exa', 'https://jobs.ashbyhq.com/exa', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2274892218%22%5D',
  }),
  createBackendScraperCompany('trajectory', 'Trajectory', 'https://jobs.ashbyhq.com/trajectory', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('krea', 'Krea', 'https://jobs.ashbyhq.com/krea', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2283009299%22%5D',
  }),
  createBackendScraperCompany('vizcom', 'Vizcom', 'https://jobs.ashbyhq.com/vizcom', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2274908198%22%5D',
  }),
  createBackendScraperCompany('posthog', 'PostHog', 'https://jobs.ashbyhq.com/posthog', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2237415928%22%5D',
  }),
  // The Interaction Company of California (makers of Poke). Ashby board slug is
  // 'interaction' (board_token), surfaced here as 'Poke'.
  createBackendScraperCompany('poke', 'Poke', 'https://jobs.ashbyhq.com/interaction', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22106772435%22%5D',
  }),
  createBackendScraperCompany('sierra', 'Sierra', 'https://jobs.ashbyhq.com/Sierra', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2299351559%22%5D',
  }),
  createBackendScraperCompany('workweave', 'Workweave', 'https://jobs.ashbyhq.com/workweave', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22102726930%22%5D',
  }),
  createBackendScraperCompany('reducto', 'Reducto', 'https://reducto.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22100163306%22%5D',
  }),
  createBackendScraperCompany('console', 'Console', 'https://console.com/careers', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('workos', 'WorkOS', 'https://jobs.ashbyhq.com/workos', {
    sourceAts: 'ashby',
  }),
  createBackendScraperCompany('salient', 'Salient', 'https://jobs.ashbyhq.com/salient', {
    sourceAts: 'ashby',
  }),

  // Gem (backend-scraper) — backend Procrastinate worker fetches from
  // api.gem.com/job_board/v0/<id>/job_posts/ on a 30-min cron. See
  // docs/implementations/gemBackendMigration/PLAN.md.
  createBackendScraperCompany(
    'nominal',
    'Nominal',
    'https://jobs.gem.com/nominal',
    {
      sourceAts: 'gem',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2292924343%22%5D',
    }
  ),
  createBackendScraperCompany(
    'retool',
    'Retool',
    'https://jobs.gem.com/retool',
    {
      sourceAts: 'gem',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2211869260%22%5D',
    }
  ),
  createBackendScraperCompany(
    'gem',
    'Gem',
    'https://jobs.gem.com/gem',
    {
      sourceAts: 'gem',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218373097%22%5D',
    }
  ),

  // Workday companies (migrated to backend-scraper)
  createBackendScraperCompany(
    'nvidia',
    'NVIDIA',
    'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223608%22%5D',
    }
  ),
  createBackendScraperCompany(
    'adobe',
    'Adobe',
    'https://adobe.wd5.myworkdayjobs.com/external_experienced',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221480%22%5D',
    }
  ),
  createBackendScraperCompany(
    'expedia',
    'Expedia',
    'https://expedia.wd108.myworkdayjobs.com/search',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222751%22%5D',
    }
  ),
  createBackendScraperCompany(
    'turo',
    'Turo',
    'https://turo.wd12.myworkdayjobs.com/Turo_careers',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%226645688%22%5D',
    }
  ),
  createBackendScraperCompany(
    'blueorigin',
    'Blue Origin',
    'https://blueorigin.wd5.myworkdayjobs.com/BlueOrigin',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2240018%22%5D',
    }
  ),
  createBackendScraperCompany(
    'snap',
    'Snap',
    'https://snapchat.wd1.myworkdayjobs.com/snap',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2215191764%22%5D',
    }
  ),
  createBackendScraperCompany(
    'gm',
    'General Motors',
    'https://generalmotors.wd5.myworkdayjobs.com/Careers_GM',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221472%22%5D',
    }
  ),
  createBackendScraperCompany(
    'disney',
    'Disney',
    'https://disney.wd5.myworkdayjobs.com/disneycareer',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221292%22%5D',
    }
  ),
  createBackendScraperCompany(
    'slack',
    'Slack',
    'https://salesforce.wd12.myworkdayjobs.com/Slack',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221612748%22%5D',
    }
  ),
  createBackendScraperCompany(
    'capitalone',
    'Capital One',
    'https://capitalone.wd12.myworkdayjobs.com/Capital_One',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221419%22%5D',
    }
  ),
  createBackendScraperCompany(
    'paypal',
    'PayPal',
    'https://paypal.wd1.myworkdayjobs.com/jobs',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221482%22%5D',
    }
  ),

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
  Console = 'console',
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
  Exa = 'exa',
  Expedia = 'expedia',
  Fal = 'fal',
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
  Krea = 'krea',
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
  PostHog = 'posthog',
  Pylon = 'pylon-labs',
  Pinterest = 'pinterest',
  Plaid = 'plaid',
  Poke = 'poke',
  Ramp = 'ramp',
  Reddit = 'reddit',
  Reducto = 'reducto',
  ResolveAI = 'resolve-ai',
  Roadrunner = 'roadrunner',
  Robinhood = 'robinhood',
  Roblox = 'roblox',
  Salient = 'salient',
  Saronic = 'saronic',
  Scaleai = 'scaleai',
  Sesame = 'sesame',
  Sentry = 'sentry',
  Sierra = 'sierra',
  SiftStack = 'siftstack',
  Slack = 'slack',
  Snap = 'snap',
  Snowflake = 'snowflake',
  Spacex = 'spacex',
  Spotify = 'spotify',
  Squarespace = 'squarespace',
  Stripe = 'stripe',
  Sunday = 'sunday',
  Supabase = 'supabase',
  ThinkingMachines = 'thinkingmachines',
  TogetherAI = 'togetherai',
  Trajectory = 'trajectory',
  Traversal = 'traversal',
  Twilio = 'twilio',
  Turo = 'turo',
  Twitch = 'twitch',
  Unity = 'unity3d',
  Vercel = 'vercel',
  Vizcom = 'vizcom',
  Waymo = 'waymo',
  WisprFlow = 'wispr-flow',
  WorkOS = 'workos',
  Workweave = 'workweave',
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
 * Public URL for a company's brand icon (square mark).
 *
 * Icons are committed as static assets under `public/logos/icons/<id>.png`
 * (served from the deploy root) and keyed by the company `id`. The file is not
 * guaranteed to exist — companies added to the backend before a logo is dropped
 * in won't have one — so consumers must render a fallback when the image fails
 * to load (see the shared `CompanyLogo` component).
 */
export function getCompanyLogoUrl(id: string): string {
  return `/logos/icons/${encodeURIComponent(id)}.png`;
}

/**
 * Public URL for a company's brand wordmark (the wide logo that includes the
 * company name). Committed as static assets under
 * `public/logos/wordmarks/<id>.png` and keyed by the company `id`. As with the
 * icon, the file is not guaranteed to exist, so consumers must render a fallback
 * when the image fails to load (see the shared `CompanyWordmark` component).
 */
export function getCompanyWordmarkUrl(id: string): string {
  return `/logos/wordmarks/${encodeURIComponent(id)}.png`;
}

/**
 * Coming soon companies for custom scrapers section
 */
export const COMING_SOON_SCRAPERS: readonly { name: string; jobsUrl: string }[] = [];
