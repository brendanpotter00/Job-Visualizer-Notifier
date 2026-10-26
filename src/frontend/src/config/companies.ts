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
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223254263%22%5D',
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
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22265314%22%5D',
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
  createBackendScraperCompany('vercel', 'Vercel', 'https://boards.greenhouse.io/vercel', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2216181286%22%5D',
  }),
  createBackendScraperCompany('togetherai', 'Together AI', 'https://boards.greenhouse.io/togetherai', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2289816302%22%5D',
  }),
  createBackendScraperCompany('roblox', 'Roblox', 'https://boards.greenhouse.io/roblox', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22147977%22%5D',
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

  // Batch add (2026-09-02) — Warp (Greenhouse; distinct from the unrelated Ashby
  // `warp` board), Coinbase, and the Jane Street quant board. board_token == id
  // for all three; see the seed migration.
  createBackendScraperCompany('warp', 'Warp', 'https://www.warp.dev/careers', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2274678194%22%5D',
  }),
  createBackendScraperCompany('coinbase', 'Coinbase', 'https://www.coinbase.com/careers/positions', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222857634%22%5D',
  }),
  createBackendScraperCompany('janestreet', 'Jane Street', 'https://www.janestreet.com/join-jane-street/open-roles/', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221713404%22%5D',
  }),

  // Batch add 2 (2026-09-02) — Okta and Box (Greenhouse). Box's board_token is
  // `boxinc`, NOT `box` (which 404s) — the real token lives in the seed migration.
  createBackendScraperCompany('okta', 'Okta', 'https://www.okta.com/company/careers/', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22926041%22%5D',
  }),
  createBackendScraperCompany('box', 'Box', 'https://careers.box.com', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2254178%22%5D',
  }),

  // Batch add (2026-09-09) — the Madrona IA40 2026 cohort, Greenhouse boards.
  // board_token == id for both; verified live (HTTP 200 with postings).
  // Gradial has no careers page of its own — gradial.com/careers 404s and the
  // site footer links straight at the Greenhouse board, so that is the jobsUrl.
  createBackendScraperCompany('gradial', 'Gradial', 'https://boards.greenhouse.io/gradial', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2295681476%22%5D',
  }),
  createBackendScraperCompany('heygen', 'HeyGen', 'https://www.heygen.com/careers', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2282350899%22%5D',
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
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%227597308%22%5D',
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
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2296134922%22%5D',
  }),
  createBackendScraperCompany('clickup', 'ClickUp', 'https://careers.ashbyhq.com/clickup', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2212949663%22%5D',
  }),
  createBackendScraperCompany('apex-technology-inc', 'Apex Technology Inc', 'https://careers.ashbyhq.com/apex-technology-inc', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2289486521%22%5D',
  }),
  createBackendScraperCompany('light', 'Light', 'https://careers.ashbyhq.com/light', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22107486267%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2293812541%22%5D',
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
  createBackendScraperCompany('resolve-ai', 'Resolve AI', 'https://jobs.ashbyhq.com/resolveai', {
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22109946185%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22108761911%22%5D',
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
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22113251209%22%5D',
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
  createBackendScraperCompany('sierra', 'Sierra', 'https://jobs.ashbyhq.com/Sierra', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2299351559%22%5D',
  }),
  createBackendScraperCompany('bedrock-robotics', 'Bedrock Robotics', 'https://jobs.ashbyhq.com/bedrock-robotics', {
    sourceAts: 'ashby',
  }),
  // Rebranded to Weave / WeaveOS on ~2026-09-23; the Ashby board moved from
  // slug `workweave` to `weave-os` and the old slug now 404s. The `id`, the
  // COMPANY_IDS member and the display name stay put: `id` is the PK and the
  // logo lookup key, and the logo art under public/logos/*/workweave.png is
  // still the Workweave wordmark. Renaming the company is a separate,
  // art-dependent change — see migration 593e96381b3e.
  createBackendScraperCompany('workweave', 'Workweave', 'https://jobs.ashbyhq.com/weave-os', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22102726930%22%5D',
  }),
  createBackendScraperCompany('reducto', 'Reducto', 'https://reducto.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22100163306%22%5D',
  }),
  // `console` was removed here on 2026-09-15 (acquired by Palo Alto Networks,
  // board emptied). The COMPANIES entry and its COMPANY_IDS member go; the
  // `companies` row stays with enabled=FALSE — the unity3d/poke soft-disable
  // precedent, see migration 7e2c9a4b51df.
  createBackendScraperCompany('workos', 'WorkOS', 'https://jobs.ashbyhq.com/workos', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2240057919%22%5D',
  }),
  createBackendScraperCompany('salient', 'Salient', 'https://jobs.ashbyhq.com/salient', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2298799140%22%5D',
  }),
  createBackendScraperCompany('parallel', 'Parallel', 'https://jobs.ashbyhq.com/parallel', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22103743985%22%5D',
  }),
  createBackendScraperCompany('factory', 'Factory', 'https://jobs.ashbyhq.com/factory', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2293213132%22%5D',
  }),
  // Migrated off Greenhouse to Ashby (2026-07-30 and 2026-08-05). The
  // Greenhouse boards 404'd/emptied after the companies moved ATS; the JVN
  // `id` is unchanged (it is the PK + logo key), only the board token moved:
  //   appliedintuition -> ashby token `applied`           (2026-07-30)
  //   fal              -> ashby token `fal-ai`            (2026-07-30)
  //   merge            -> ashby token `merge`             (2026-07-30)
  //   fireworksai      -> ashby token `fireworks`         (2026-08-05)
  //   thinkingmachines -> ashby token `thinkingmachines`  (2026-08-05)
  //   hightouch        -> ashby token `hightouch-inc`     (2026-10-02)
  // Backend counterpart: the repoint migrations in src/backend/alembic/versions/.
  // hightouch's token is `hightouch-inc`, NOT `hightouch`: the bare `hightouch`
  // Ashby board also answers 200, but with a single 2021 posting left over from
  // a board they abandoned. Verified live 2026-10-02 — `hightouch-inc` serves 82
  // jobs, matching hightouch.com/careers exactly.
  createBackendScraperCompany('appliedintuition', 'Applied Intuition', 'https://jobs.ashbyhq.com/applied', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218808325%22%5D',
  }),
  createBackendScraperCompany('fal', 'fal', 'https://jobs.ashbyhq.com/fal-ai', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2277745852%22%5D',
  }),
  createBackendScraperCompany('merge', 'Merge', 'https://jobs.ashbyhq.com/merge', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2253197721%22%5D',
  }),
  createBackendScraperCompany('fireworksai', 'Fireworks AI', 'https://jobs.ashbyhq.com/fireworks', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2291174981%22%5D',
  }),
  createBackendScraperCompany('thinkingmachines', 'Thinking Machines', 'https://jobs.ashbyhq.com/thinkingmachines', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22105913171%22%5D',
  }),
  createBackendScraperCompany('hightouch', 'Hightouch', 'https://jobs.ashbyhq.com/hightouch-inc', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2242344868%22%5D',
  }),

  // Batch add (2026-09-02) — Ashby boards (every token verified live). Note the
  // JVN id differs from the ATS board_token for physical-intelligence
  // (physicalintelligence), mistral-ai (mistral.ai) and clay (claylabs) — the
  // backend seed migration holds the real tokens.
  createBackendScraperCompany('suno', 'Suno', 'https://jobs.ashbyhq.com/suno', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2281884275%22%5D',
  }),
  createBackendScraperCompany('cerebras', 'Cerebras', 'https://www.cerebras.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2210858000%22%5D',
  }),
  createBackendScraperCompany('physical-intelligence', 'Physical Intelligence', 'https://www.physicalintelligence.company/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22100923057%22%5D',
  }),
  createBackendScraperCompany('mistral-ai', 'Mistral AI', 'https://jobs.ashbyhq.com/mistral.ai', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2294273421%22%5D',
  }),
  createBackendScraperCompany('replit', 'Replit', 'https://replit.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218542592%22%5D',
  }),
  createBackendScraperCompany('railway', 'Railway', 'https://railway.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2265574467%22%5D',
  }),
  createBackendScraperCompany('crusoe', 'Crusoe', 'https://jobs.ashbyhq.com/Crusoe', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2219150725%22%5D',
  }),
  createBackendScraperCompany('raindrop-ai', 'Raindrop', 'https://jobs.ashbyhq.com/raindrop', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22101675721%22%5D',
  }),
  createBackendScraperCompany('wafer', 'Wafer', 'https://jobs.ashbyhq.com/wafer', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22107522822%22%5D',
  }),
  createBackendScraperCompany('clay', 'Clay', 'https://www.clay.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2213018048%22%5D',
  }),
  createBackendScraperCompany('turbopuffer', 'turbopuffer', 'https://turbopuffer.com/jobs', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2299554344%22%5D',
  }),
  createBackendScraperCompany('openevidence', 'OpenEvidence', 'https://jobs.ashbyhq.com/openevidence', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2281917876%22%5D',
  }),
  createBackendScraperCompany('greptile', 'Greptile', 'https://www.greptile.com/careers/open', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2280034057%22%5D',
  }),

  // Batch add (2026-09-07) — Ashby boards (every token verified live: HTTP 200
  // with postings). The JVN id differs from the ATS board_token for ploy
  // (`ployai`; bare `ploy` 404s) — the backend seed migration holds the real
  // token. `sieve` kept its Ashby slug through the sievedata.com -> sieve.ai
  // rebrand (`sievedata` 404s), and `taste-labs` is hyphenated and
  // case-sensitive (bare `tastelabs` 404s).
  createBackendScraperCompany('composio', 'Composio', 'https://composio.dev/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22100723307%22%5D',
  }),
  createBackendScraperCompany('listenlabs', 'Listen Labs', 'https://listenlabs.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2295038218%22%5D',
  }),
  createBackendScraperCompany('taste-labs', 'Taste Labs', 'https://tastelabs.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22131914128%22%5D',
  }),
  createBackendScraperCompany('sieve', 'Sieve', 'https://sieve.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2276210196%22%5D',
  }),
  createBackendScraperCompany('ploy', 'Ploy', 'https://ploy.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22111250170%22%5D',
  }),

  // Batch add (2026-09-09) — the Madrona IA40 2026 cohort, Ashby boards (every
  // token verified live: HTTP 200 with postings). Two ids differ from the ATS
  // board_token, and the backend seed migration holds the real token:
  //   fable-security -> ashby token `fable`  (id disambiguated from the other
  //                     Fables; the board slug itself is the bare word)
  // Two jobsUrls point at the Ashby board rather than the company's own page,
  // because the company page does not serve one: aiuc.com/careers 404s and
  // fablesecurity.com/careers 403s to non-browser clients.
  createBackendScraperCompany('aiuc', 'AIUC', 'https://jobs.ashbyhq.com/aiuc', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22106689250%22%5D',
  }),
  createBackendScraperCompany('cartesia', 'Cartesia', 'https://cartesia.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2299079767%22%5D',
  }),
  createBackendScraperCompany('clarify', 'Clarify', 'https://clarify.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2299278604%22%5D',
  }),
  createBackendScraperCompany('clickhouse', 'ClickHouse', 'https://clickhouse.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2280114151%22%5D',
  }),
  createBackendScraperCompany('coderabbit', 'CodeRabbit', 'https://www.coderabbit.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2297023698%22%5D',
  }),
  createBackendScraperCompany(
    'fable-security',
    'Fable Security',
    'https://jobs.ashbyhq.com/fable',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22100956717%22%5D',
    }
  ),
  createBackendScraperCompany('gamma', 'Gamma', 'https://careers.gamma.app', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2274998228%22%5D',
  }),
  createBackendScraperCompany('gimlet', 'Gimlet', 'https://www.gimletlabs.ai/join_us', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22102691744%22%5D',
  }),
  createBackendScraperCompany('legora', 'Legora', 'https://legora.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2293196471%22%5D',
  }),
  createBackendScraperCompany('lovable', 'Lovable', 'https://lovable.dev/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22101649602%22%5D',
  }),
  createBackendScraperCompany('mastra', 'Mastra', 'https://mastra.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22104974021%22%5D',
  }),
  createBackendScraperCompany('openrouter', 'OpenRouter', 'https://openrouter.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22104068329%22%5D',
  }),
  createBackendScraperCompany('profound', 'Profound', 'https://www.tryprofound.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22104065246%22%5D',
  }),
  createBackendScraperCompany('resend', 'Resend', 'https://resend.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2288424181%22%5D',
  }),
  createBackendScraperCompany('serval', 'Serval', 'https://www.serval.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22101771821%22%5D',
  }),
  createBackendScraperCompany('simile', 'Simile', 'https://www.simile.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22107803218%22%5D',
  }),
  createBackendScraperCompany('town', 'Town', 'https://town.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22106390409%22%5D',
  }),
  createBackendScraperCompany('zed', 'Zed', 'https://zed.dev/jobs', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2290666371%22%5D',
  }),

  // The JVN id is `tomo-ai`, NOT `tomo`, and the distinction is load-bearing:
  // `jobs.ashbyhq.com/tomo` is a DIFFERENT company — the Tomo mortgage lender,
  // hiring Loan Officers and Underwriters — and it also returns HTTP 200, so a
  // status code alone picks the wrong one. The board_token in the seed
  // migration is `tomo.ai` (with the dot); verified live against the job UUID
  // in the posting URL this was added from.
  createBackendScraperCompany('tomo-ai', 'Tomo', 'https://jobs.ashbyhq.com/tomo.ai', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22117004846%22%5D',
  }),
  createBackendScraperCompany('tavus', 'Tavus', 'https://jobs.ashbyhq.com/tavus', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2274447778%22%5D',
  }),
  // The id carries `-ai` because `typesafe` alone is ambiguous: Typesafe was the
  // FORMER NAME OF LIGHTBEND, the Scala/Akka company. The bare token 404s too
  // (`typesafe` and `typesafeai` both), so `typesafe-ai` is the only live slug
  // as well as the unambiguous one.
  createBackendScraperCompany('typesafe-ai', 'TypeSafe', 'https://jobs.ashbyhq.com/typesafe-ai', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22103805719%22%5D',
  }),
  // The board slug is `david-ai` but the company's site is withdavid.ai, and
  // NEITHER is guessable from the other — `withdavid`, `david`, `with-david`,
  // `withdavidai` and `davidai` all 404. The slug came out of the careers page
  // itself (`ashbyBaseJobBoardUrl`), and was confirmed by the job id in the URL
  // this was added from resolving on that board.
  createBackendScraperCompany('david-ai', 'David AI', 'https://www.withdavid.ai/jobs', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22103067205%22%5D',
  }),
  // Ashby serves this board under BOTH `Blacksmith` and `blacksmith` (verified,
  // same 20 postings either way), so the capital in the careers URL is not a
  // second board. The lowercase token is stored, matching every other entry —
  // the skill's per-ATS table calls Ashby tokens case-sensitive, which is true
  // in general even though this tenant tolerates both.
  createBackendScraperCompany('blacksmith', 'Blacksmith', 'https://jobs.ashbyhq.com/Blacksmith', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2299471972%22%5D',
  }),
  // Identity proven, not inferred: the job id in the posting URL this was added
  // from (e8168e8a-451e-41bb-9c13-8f24b4b84e50) resolves on the `llamaindex`
  // board as "Member of Technical Staff, Infrastructure".
  createBackendScraperCompany('llamaindex', 'LlamaIndex', 'https://www.llamaindex.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2291154103%22%5D',
  }),
  // The agent-native team-messaging startup at ando.so (the board's own
  // `publicWebsite`), NOT David Chang's 2016 Ando food-delivery app that Uber
  // Eats acquired in 2018. The careers URL is the board itself: ando.so has no
  // careers page (/careers and /jobs both 404).
  createBackendScraperCompany('ando', 'Ando', 'https://jobs.ashbyhq.com/ando', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223871272%22%5D',
  }),
  // All 31 job ids linked from firecrawl.dev/careers resolve on the `firecrawl`
  // board, so the careers page and the board are the same set.
  createBackendScraperCompany('firecrawl', 'Firecrawl', 'https://www.firecrawl.dev/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22104100957%22%5D',
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
  // Batch add (2026-09-09) — the Madrona IA40 2026 cohort. fireflies.ai/careers
  // 307-redirects to jobs.gem.com/fireflies; board_token == id, verified live.
  createBackendScraperCompany(
    'fireflies',
    'Fireflies.ai',
    'https://fireflies.ai/careers',
    {
      sourceAts: 'gem',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2210931378%22%5D',
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

  // Batch add (2026-09-02) — Workday. provider_config lives in the backend seed
  // migration (pod wd5, career-site slug Cisco_Careers).
  createBackendScraperCompany(
    'cisco',
    'Cisco',
    'https://cisco.wd5.myworkdayjobs.com/Cisco_Careers',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221063%22%5D',
    }
  ),

  // Batch add 2 (2026-09-02) — Salesforce, CrowdStrike, Zoom, Intel (Workday).
  // Each carries a provider_config in the seed migration; the wdN pod is
  // load-bearing (wd12 / wd5 / wd5 / wd1 respectively — a wrong pod fetches 0).
  createBackendScraperCompany(
    'salesforce',
    'Salesforce',
    'https://salesforce.wd12.myworkdayjobs.com/External_Career_Site',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%223185%22%5D',
    }
  ),
  createBackendScraperCompany(
    'crowdstrike',
    'CrowdStrike',
    'https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222497653%22%5D',
    }
  ),
  createBackendScraperCompany(
    'zoom',
    'Zoom',
    'https://careers.zoom.us',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%222532259%22%5D',
    }
  ),
  createBackendScraperCompany(
    'intel',
    'Intel',
    'https://intel.wd1.myworkdayjobs.com/External',
    {
      sourceAts: 'workday',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221053%22%5D',
    }
  ),

  // Backend scraper companies (formerly Eightfold)
  createBackendScraperCompany('netflix', 'Netflix', 'https://explore.jobs.netflix.net/', {
    sourceAts: 'eightfold',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22165158%22%5D',
  }),

  // Backend scraper companies (Python-scraped: Google, Apple, Microsoft,
  // Amazon, TikTok). These deliberately omit `sourceAts` — that absence is what
  // groups them under "Custom Web Scrapers" (see config/atsSource.ts).
  createBackendScraperCompany('amazon', 'Amazon', 'https://www.amazon.jobs/', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221586%22%5D',
  }),
  createBackendScraperCompany('google', 'Google', 'https://careers.google.com/', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221441%22%5D',
  }),
  createBackendScraperCompany('apple', 'Apple', 'https://jobs.apple.com/', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22162479%22%5D',
  }),
  createBackendScraperCompany('microsoft', 'Microsoft', 'https://careers.microsoft.com/', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221035%22%5D',
  }),
  createBackendScraperCompany('tiktok', 'TikTok', 'https://lifeattiktok.com/search', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2233246798%22%5D',
  }),
  createBackendScraperCompany('meta', 'Meta', 'https://www.metacareers.com/jobs', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2210667%22%5D',
  }),

  // Recipe boards (2026-09-09) — bespoke career sites read by the deterministic
  // replay engine (`companies.ats='recipe'`), not by a vendor ATS client and not
  // by a Python scraper. Each one's stored script lives in `company_scripts` and
  // is committed alongside at
  // `src/backend/api/tests/fixtures/recipes/published/<id>.json`.
  //
  // They omit `sourceAts` for the same reason the Python-scraped five above do:
  // that absence is what groups them under "Custom Web Scrapers", and the union
  // type deliberately names only the six vendor ATSes. Do NOT add 'recipe' to it
  // — `sourceAts` answers "which vendor board is behind this", and the answer
  // here is genuinely none.
  createBackendScraperCompany('atlassian', 'Atlassian', 'https://www.atlassian.com/company/careers/all-jobs', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2222688%22%5D',
  }),
  createBackendScraperCompany('github', 'GitHub', 'https://www.github.careers/careers-home/jobs', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%221418841%22%5D',
  }),

  // Lightfield (lightfield.app)
  createBackendScraperCompany('lightfield', 'Lightfield', 'https://jobs.ashbyhq.com/Lightfield', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22106407337%22%5D',
  }),

  // Arena (arena.ai)
  createBackendScraperCompany('arena', 'Arena', 'https://jobs.ashbyhq.com/arena', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22107123113%22%5D',
  }),

  // Batch add (2026-10-21) — hand-picked boards, each verified live on the day it
  // was added.
  createBackendScraperCompany('attio', 'Attio', 'https://attio.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2214815603%22%5D',
  }),
  // Ghost the personal-AI hardware startup at ghost.ai (the Core device) — NOT
  // ghost.org, the open-source publishing platform. Proven by the posting this was added
  // from (a286999a-…) resolving on the `ghost` board.
  createBackendScraperCompany('ghost', 'Ghost', 'https://ghost.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22110953336%22%5D',
  }),
  createBackendScraperCompany('hex', 'Hex', 'https://hex.tech/careers/', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2269022212%22%5D',
  }),
  createBackendScraperCompany('melius', 'Melius', 'https://jobs.ashbyhq.com/melius', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22108443940%22%5D',
  }),
  createBackendScraperCompany('momentic', 'Momentic', 'https://jobs.ashbyhq.com/momentic', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2298519062%22%5D',
  }),
  createBackendScraperCompany('render', 'Render', 'https://render.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2218594249%22%5D',
  }),
  // The company behind World (the Orb, World ID). Its Ashby token CONTAINS SPACES —
  // `tools for humanity` (toolsforhumanity.com/careers links `Tools%20for%20Humanity`;
  // both casings serve the same postings, the lowercase one is stored) — and every
  // joined or hyphenated spelling 404s, as does `worldcoin`. httpx percent-encodes
  // the spaces in the backend's f-string URL, same as `ricursive-intelligence` below.
  createBackendScraperCompany(
    'tools-for-humanity',
    'Tools for Humanity',
    'https://www.toolsforhumanity.com/careers',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2290410174%22%5D',
    }
  ),

  // Batch add (2026-10-21) — Greenfield Partners' Disruptors 60, Class of 2026 plus
  // the 2026 Pioneers we did not already track (disruptors60.ai/winners/2026).
  // Every board_token verified live on the day it was added (HTTP 200 JSON). The
  // D60 companies on unsupported ATSes (Comeet, Workable, custom pages, …) are
  // listed in the PR that added this block, not here.

  // The Ashby board is live but lists no roles yet; it is tracked so postings show up
  // the day they are published. accomplish.ai has no careers page (every path 404s).
  createBackendScraperCompany('accomplish', 'Accomplish', 'https://jobs.ashbyhq.com/accomplish', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22111126113%22%5D',
  }),
  createBackendScraperCompany('boltz', 'Boltz', 'https://jobs.gem.com/boltz', {
    sourceAts: 'gem',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22110446491%22%5D',
  }),
  createBackendScraperCompany('callosum', 'Callosum', 'https://www.callosum.com/join-us', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22110752928%22%5D',
  }),
  // Ashby token `chaidiscovery` — the hyphenated `chai-discovery` 404s.
  createBackendScraperCompany(
    'chai-discovery',
    'Chai Discovery',
    'https://www.chaidiscovery.com/careers',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22104933279%22%5D',
    }
  ),
  createBackendScraperCompany(
    'code-metal',
    'Code Metal',
    'https://www.codemetal.ai/company#open-roles',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22101825776%22%5D',
    }
  ),
  createBackendScraperCompany('como', 'COMO', 'https://como.io/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22145230498%22%5D',
  }),
  createBackendScraperCompany('conduct', 'Conduct', 'https://conduct.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22103435439%22%5D',
  }),
  // Corma the AI-for-defensive-security lab at corma.ai — NOT corma.io, the French
  // access-management SaaS. Tied by the board's own `publicWebsite`. The board is live
  // but lists no roles yet; corma.ai has no careers page.
  createBackendScraperCompany('corma', 'Corma', 'https://jobs.ashbyhq.com/corma', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22135663975%22%5D',
  }),
  // IDENTITY TRAP: Ashby `corridor` is a DIFFERENT Corridor (corridor.dev, an AI
  // security product). This is the benefits brokerage at corridoradvisors.com, whose
  // board is `corridor-advisors` (`corridoradvisors` 404s).
  createBackendScraperCompany('corridor', 'Corridor', 'https://corridoradvisors.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22111886635%22%5D',
  }),
  createBackendScraperCompany('duvo', 'Duvo', 'https://www.duvo.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22107577785%22%5D',
  }),
  createBackendScraperCompany('dwelly', 'Dwelly', 'https://www.dwelly.group/careers', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22104483733%22%5D',
  }),
  createBackendScraperCompany('endra', 'Endra', 'https://www.endra.ai/career', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22106335430%22%5D',
  }),
  createBackendScraperCompany('engram', 'Engram', 'https://engram.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2246890012%22%5D',
  }),
  createBackendScraperCompany('etched', 'Etched', 'https://www.etched.com/join', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2293620799%22%5D',
  }),
  createBackendScraperCompany(
    'foundry-robotics',
    'Foundry Robotics',
    'https://jobs.ashbyhq.com/foundry-robotics',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22111491132%22%5D',
    }
  ),
  createBackendScraperCompany('fundamental', 'Fundamental', 'https://fundamental.tech/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22111252017%22%5D',
  }),
  // Glow the endpoint-AI security company (glow.io), id disambiguated from the bare
  // word. Ashby token `glow`. A Greenhouse `glow` board also answers 200, with 0 jobs
  // and no link from glow.io — not this company's board.
  createBackendScraperCompany('glow-security', 'Glow', 'https://www.glow.io/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22118894433%22%5D',
  }),
  // Ashby token `hadrian-automation` — the bare `hadrian` 404s.
  createBackendScraperCompany('hadrian', 'Hadrian', 'https://www.hadrian.co/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2271668100%22%5D',
  }),
  createBackendScraperCompany('hemispheric', 'Hemispheric', 'https://www.hemispheric.ai/careers', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22105462551%22%5D',
  }),
  // Ashby serves this board as both `Irregular` (the casing irregular.com links) and
  // `irregular`, same postings; the lowercase token is stored.
  createBackendScraperCompany('irregular', 'Irregular', 'https://www.irregular.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22101418756%22%5D',
  }),
  createBackendScraperCompany('lawhive', 'Lawhive', 'https://jobs.ashbyhq.com/lawhive', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2271253922%22%5D',
  }),
  createBackendScraperCompany('lio', 'Lio', 'https://www.lio.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2293327386%22%5D',
  }),
  createBackendScraperCompany('livekit', 'LiveKit', 'https://livekit.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2274724401%22%5D',
  }),
  // Ashby serves this board as both `NormalComputing` (the hosted-page casing
  // careers.normalcomputing.com redirects to) and `normalcomputing`, same postings; the
  // lowercase token is stored. The hyphenated `normal-computing` 404s.
  createBackendScraperCompany(
    'normal-computing',
    'Normal Computing',
    'https://careers.normalcomputing.com',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2292930537%22%5D',
    }
  ),
  createBackendScraperCompany('nox-metals', 'Nox Metals', 'https://noxmetals.co/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22107769143%22%5D',
  }),
  createBackendScraperCompany('ornn', 'Ornn', 'https://ornn.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2293871334%22%5D',
  }),
  // Pace the insurance-operations AI company at withpace.com. Ashby token `withpace`
  // (`pace` 404s); its open roles live on /company — /careers 404s.
  createBackendScraperCompany('pace', 'Pace', 'https://www.withpace.com/company', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22108030616%22%5D',
  }),
  // IDENTITY TRAP: Ashby `patronus` is Patronus Group (Berlin, patronus-group.com),
  // not this company. Patronus AI hires through Greenhouse as `patronusaiinc`.
  createBackendScraperCompany('patronus-ai', 'Patronus AI', 'https://www.patronus.ai/join', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2298695525%22%5D',
  }),
  createBackendScraperCompany(
    'periodic-labs',
    'Periodic Labs',
    'https://jobs.ashbyhq.com/periodic-labs',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22108918379%22%5D',
    }
  ),
  createBackendScraperCompany('probook', 'Probook', 'https://www.probook.ai/company#open-roles', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2293780122%22%5D',
  }),
  createBackendScraperCompany('revel', 'Revel', 'https://www.revel.io/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22106558023%22%5D',
  }),
  // The Ashby token CONTAINS A SPACE: the board is named `ricursive intelligence`
  // (Ashby's own job URLs spell it `ricursive%20intelligence`). Every hyphenated or
  // joined spelling 404s. The backend's f-string URL is percent-encoded by httpx, so
  // the decoded form is what the seed migration stores.
  createBackendScraperCompany(
    'ricursive-intelligence',
    'Ricursive Intelligence',
    'https://www.ricursive.com/careers',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22110225045%22%5D',
    }
  ),
  // Scope the industrial-inspection AI company at getscope.ai. Ashby token `getscope`
  // (`scope` 404s); its careers page is getscope.ai/career, singular — /careers 404s.
  createBackendScraperCompany('scope', 'Scope', 'https://www.getscope.ai/career', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22103396277%22%5D',
  }),
  createBackendScraperCompany('sphere', 'Sphere', 'https://www.getsphere.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2269773723%22%5D',
  }),
  createBackendScraperCompany('starbridge', 'Starbridge', 'https://jobs.ashbyhq.com/starbridge', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22105986429%22%5D',
  }),
  createBackendScraperCompany('surge-ai', 'Surge AI', 'https://surgehq.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2267755934%22%5D',
  }),
  createBackendScraperCompany('westmag', 'Westmag', 'https://www.westmag.com/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22116334022%22%5D',
  }),
  // Ashby token `wordsmith` — `wordsmith-ai` and `wordsmithai` 404.
  createBackendScraperCompany('wordsmith-ai', 'Wordsmith AI', 'https://www.wordsmith.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22102875272%22%5D',
  }),
  createBackendScraperCompany('xdof', 'XDOF', 'https://www.xdof.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22104424356%22%5D',
  }),

  // Batch add (2026-10-22) — hand-picked boards, each verified live on the day it
  // was added. (Whatnot was asked for too, but its Ashby board has the public
  // posting API switched off, so no supported client can read it.)
  // The research-automation lab Jeff Dean, Sanjay Ghemawat, Quoc Le and Oriol Vinyals
  // started in 2026 (discoveryloop.com — the board's own publicWebsite). Ashby serves the
  // board as both `Discovery-Loop` (its hosted-page casing) and `discovery-loop`; the
  // lowercase token is stored. discoveryloop.com/careers 404s, so the board URL is used.
  createBackendScraperCompany(
    'discovery-loop',
    'Discovery Loop',
    'https://jobs.ashbyhq.com/Discovery-Loop',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22143069977%22%5D',
    }
  ),
  // Generalist the robotics foundation-model lab (generalistai.com), not The Generalist
  // newsletter; the id carries the fuller name, the Ashby token is the bare `generalist`.
  createBackendScraperCompany(
    'generalist-ai',
    'Generalist AI',
    'https://generalistai.com/careers',
    {
      sourceAts: 'ashby',
      recruiterLinkedInUrl:
        'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22105854178%22%5D',
    }
  ),
  // humans& (humansand.ai), the human-centric AI lab — lowercase with the ampersand is
  // its own spelling. humansand.ai has no careers page; its Join Us link is the board.
  createBackendScraperCompany('humans-and', 'humans&', 'https://jobs.ashbyhq.com/humans-and', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22109358162%22%5D',
  }),
  // Greenhouse token `k2spacecorporation` — `k2space` is not its board.
  createBackendScraperCompany('k2-space', 'K2 Space', 'https://www.k2space.com/careers', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2290594574%22%5D',
  }),
  // kalshi.com/careers rate-limits non-browser clients (429), so the board URL is used.
  createBackendScraperCompany('kalshi', 'Kalshi', 'https://job-boards.greenhouse.io/kalshi', {
    sourceAts: 'greenhouse',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2219087660%22%5D',
  }),
  // Reflection AI the open-weight model lab (reflection.ai), not Reflection 70B or the
  // reflection.app journal. Ashby token `reflectionai`.
  createBackendScraperCompany('reflection-ai', 'Reflection AI', 'https://reflection.ai/careers', {
    sourceAts: 'ashby',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22106009488%22%5D',
  }),
  // Lever token `shieldai`. Its careers page also links a separate Greenhouse board for
  // Aechelon Technology (an acquisition, `aechelontechnology`), which is not tracked here.
  createBackendScraperCompany('shield-ai', 'Shield AI', 'https://shield.ai/careers/', {
    sourceAts: 'lever',
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%227952659%22%5D',
  }),
];

export const enum COMPANY_IDS {
  Accomplish = 'accomplish',
  Adobe = 'adobe',
  Affirm = 'affirm',
  Airbnb = 'airbnb',
  Airtable = 'airtable',
  Aiuc = 'aiuc',
  Amazon = 'amazon',
  Ando = 'ando',
  AndurilIndustries = 'andurilindustries',
  Anthropic = 'anthropic',
  ApexTechnologyInc = 'apex-technology-inc',
  Apple = 'apple',
  AppliedIntuition = 'appliedintuition',
  Arena = 'arena',
  Astranis = 'astranis',
  Atlassian = 'atlassian',
  Attio = 'attio',
  Baseten = 'baseten',
  BasePower = 'base-power',
  Bedrock = 'bedrock-robotics',
  Blacksmith = 'blacksmith',
  Block = 'block',
  Boltz = 'boltz',
  Box = 'box',
  BlueOrigin = 'blueorigin',
  Brex = 'brex',
  Braintrust = 'braintrust',
  Browserbase = 'browserbase',
  Callosum = 'callosum',
  CapitalOne = 'capitalone',
  Cartesia = 'cartesia',
  Cerebras = 'cerebras',
  ChaiDiscovery = 'chai-discovery',
  Chalk = 'chalk',
  Cisco = 'cisco',
  Clarify = 'clarify',
  Clay = 'clay',
  Clear = 'clear',
  ClickHouse = 'clickhouse',
  ClickUp = 'clickup',
  Cloudflare = 'cloudflare',
  CodeMetal = 'code-metal',
  CodeRabbit = 'coderabbit',
  Cognition = 'cognition',
  Cohere = 'cohere',
  Coinbase = 'coinbase',
  Como = 'como',
  Composio = 'composio',
  Conduct = 'conduct',
  Corma = 'corma',
  Corridor = 'corridor',
  CrowdStrike = 'crowdstrike',
  Crunchyroll = 'crunchyroll',
  Crusoe = 'crusoe',
  Cursor = 'cursor',
  Databricks = 'databricks',
  Decagon = 'decagon',
  Datadog = 'datadog',
  DavidAI = 'david-ai',
  Discord = 'discord',
  DiscoveryLoop = 'discovery-loop',
  Distyl = 'distyl',
  Dropbox = 'dropbox',
  Disney = 'disney',
  Doordashusa = 'doordashusa',
  Duvo = 'duvo',
  Dwelly = 'dwelly',
  ElevenLabs = 'elevenlabs',
  EliseAI = 'eliseai',
  Endra = 'endra',
  Engram = 'engram',
  Etched = 'etched',
  Exa = 'exa',
  Expedia = 'expedia',
  FableSecurity = 'fable-security',
  Factory = 'factory',
  Fal = 'fal',
  Figma = 'figma',
  FigureAI = 'figureai',
  Firecrawl = 'firecrawl',
  Fireflies = 'fireflies',
  Flint = 'flint',
  FireworksAI = 'fireworksai',
  FlowEngineering = 'flowengineering',
  FoundryRobotics = 'foundry-robotics',
  Fundamental = 'fundamental',
  Gamma = 'gamma',
  GeneralIntelligenceCompany = 'generalintelligencecompany',
  GeneralistAI = 'generalist-ai',
  GeneralMotors = 'gm',
  Ghost = 'ghost',
  GigaML = 'gigaml',
  Gimlet = 'gimlet',
  Github = 'github',
  GitLab = 'gitlab',
  Glean = 'gleanwork',
  GlowSecurity = 'glow-security',
  Google = 'google',
  Gradial = 'gradial',
  Granola = 'granola',
  Greptile = 'greptile',
  Hadrian = 'hadrian',
  Harvey = 'harvey',
  Happyrobot = 'happyrobot.ai',
  Hemispheric = 'hemispheric',
  Hex = 'hex',
  HeyGen = 'heygen',
  Hightouch = 'hightouch',
  HumansAnd = 'humans-and',
  Instacart = 'instacart',
  Intel = 'intel',
  Irregular = 'irregular',
  JaneStreet = 'janestreet',
  JudgmentLabs = 'judgmentlabs',
  K2Space = 'k2-space',
  Kalshi = 'kalshi',
  Krea = 'krea',
  LangChain = 'langchain',
  Lawhive = 'lawhive',
  Legora = 'legora',
  Light = 'light',
  Lightfield = 'lightfield',
  Linear = 'linear',
  Lio = 'lio',
  ListenLabs = 'listenlabs',
  LiveKit = 'livekit',
  LlamaIndex = 'llamaindex',
  Lovable = 'lovable',
  Lyft = 'lyft',
  Mastra = 'mastra',
  Melius = 'melius',
  Merge = 'merge',
  Meta = 'meta',
  Microsoft = 'microsoft',
  Mintlify = 'mintlify',
  MistralAI = 'mistral-ai',
  ModalLabs = 'modal',
  Momentic = 'momentic',
  MongoDB = 'mongodb',
  Netflix = 'netflix',
  Neuralink = 'neuralink',
  Nominal = 'nominal',
  NormalComputing = 'normal-computing',
  Notion = 'notion',
  NoxMetals = 'nox-metals',
  Nuro = 'nuro',
  Nvidia = 'nvidia',
  Okta = 'okta',
  OpenAI = 'openai',
  OpenEvidence = 'openevidence',
  OpenRouter = 'openrouter',
  Ornn = 'ornn',
  Pace = 'pace',
  Pallet = 'pallet',
  Palantir = 'palantir',
  Paraform = 'paraform',
  Parallel = 'parallel',
  PatronusAI = 'patronus-ai',
  PayPal = 'paypal',
  PeriodicLabs = 'periodic-labs',
  Perplexity = 'perplexity',
  PhysicalIntelligence = 'physical-intelligence',
  PostHog = 'posthog',
  Probook = 'probook',
  Pylon = 'pylon-labs',
  Pinterest = 'pinterest',
  Plaid = 'plaid',
  Ploy = 'ploy',
  Profound = 'profound',
  Railway = 'railway',
  RaindropAI = 'raindrop-ai',
  Ramp = 'ramp',
  Reddit = 'reddit',
  Reducto = 'reducto',
  ReflectionAI = 'reflection-ai',
  Render = 'render',
  Replit = 'replit',
  Resend = 'resend',
  ResolveAI = 'resolve-ai',
  Revel = 'revel',
  RicursiveIntelligence = 'ricursive-intelligence',
  Roadrunner = 'roadrunner',
  Robinhood = 'robinhood',
  Roblox = 'roblox',
  Salesforce = 'salesforce',
  Salient = 'salient',
  Saronic = 'saronic',
  Scaleai = 'scaleai',
  Scope = 'scope',
  Sesame = 'sesame',
  Sentry = 'sentry',
  Serval = 'serval',
  ShieldAI = 'shield-ai',
  Sierra = 'sierra',
  Sieve = 'sieve',
  SiftStack = 'siftstack',
  Simile = 'simile',
  Slack = 'slack',
  Snap = 'snap',
  Snowflake = 'snowflake',
  Spacex = 'spacex',
  Sphere = 'sphere',
  Spotify = 'spotify',
  Squarespace = 'squarespace',
  Starbridge = 'starbridge',
  Stripe = 'stripe',
  Sunday = 'sunday',
  Suno = 'suno',
  Supabase = 'supabase',
  SurgeAI = 'surge-ai',
  TasteLabs = 'taste-labs',
  Tavus = 'tavus',
  ThinkingMachines = 'thinkingmachines',
  TikTok = 'tiktok',
  TogetherAI = 'togetherai',
  TomoAI = 'tomo-ai',
  ToolsForHumanity = 'tools-for-humanity',
  Town = 'town',
  Trajectory = 'trajectory',
  Traversal = 'traversal',
  Turbopuffer = 'turbopuffer',
  Twilio = 'twilio',
  Turo = 'turo',
  Twitch = 'twitch',
  TypeSafe = 'typesafe-ai',
  Vercel = 'vercel',
  Vizcom = 'vizcom',
  Wafer = 'wafer',
  Warp = 'warp',
  Waymo = 'waymo',
  Westmag = 'westmag',
  WisprFlow = 'wispr-flow',
  WordsmithAI = 'wordsmith-ai',
  WorkOS = 'workos',
  Workweave = 'workweave',
  Xai = 'xai',
  Xdof = 'xdof',
  Zed = 'zed',
  Zoom = 'zoom',
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
