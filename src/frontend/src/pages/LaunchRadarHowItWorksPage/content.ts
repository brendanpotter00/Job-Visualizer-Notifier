// Content for the public "How Launch Radar works" page. Each request body is the
// exact JSON a step of scripts/launch_radar/ sends to the Parallel API, built by the
// loop's own request builders with example inputs (requestBodies.json; regenerate it
// with `python -m launch_radar.explainer`, see scripts/launch_radar/explainer.py).
// Prices and latencies are the ones recorded in docs/implementations/launch-radar/.
import REQUEST_BODIES from './requestBodies.json';

export type RequestValue =
  | string
  | number
  | boolean
  | null
  | readonly RequestValue[]
  | { readonly [key: string]: RequestValue };

export interface StepFact {
  label: string;
  value: string;
}

export type ApiStepId =
  | 'monitor'
  | 'backfillFind'
  | 'backfillEnrich'
  | 'website'
  | 'leaders'
  | 'company'
  | 'team'
  | 'leaderResearch';

/** Every box in the diagram: the eight API calls plus the free scoring step. */
export type StepId = ApiStepId | 'score';

export interface ApiStep {
  id: ApiStepId;
  title: string;
  /** The Parallel API, shown under the title in the diagram. */
  api: string;
  facts: StepFact[];
  request: RequestValue;
}

export const API_STEPS: Record<ApiStepId, ApiStep> = {
  monitor: {
    id: 'monitor',
    title: 'Find new startups',
    api: 'Monitor',
    facts: [
      { label: 'API', value: 'Monitor' },
      { label: 'Processor', value: 'base' },
      { label: 'Cost', value: '$0.01 / day' },
      { label: 'Latency', value: '~1 min' },
    ],
    request: REQUEST_BODIES.monitor,
  },
  backfillFind: {
    id: 'backfillFind',
    title: 'Find past startups',
    api: 'FindAll',
    facts: [
      { label: 'API', value: 'FindAll' },
      { label: 'Generator', value: 'base' },
      { label: 'Cost', value: '$0.25 + $0.03 / match' },
      { label: 'Latency', value: '~12 min' },
    ],
    request: REQUEST_BODIES.backfillFind,
  },
  backfillEnrich: {
    id: 'backfillEnrich',
    title: "Get each startup's announcement",
    api: 'FindAll enrich',
    facts: [
      { label: 'API', value: 'FindAll enrich' },
      { label: 'Processor', value: 'base' },
      { label: 'Cost', value: '$0.01 / match' },
      { label: 'Latency', value: '~3 min' },
    ],
    request: REQUEST_BODIES.backfillEnrich,
  },
  website: {
    id: 'website',
    title: 'Find the website',
    api: 'Search',
    facts: [
      { label: 'API', value: 'Search' },
      { label: 'Mode', value: 'advanced' },
      { label: 'Cost', value: '$0.005' },
      { label: 'Latency', value: '~3 s' },
    ],
    request: REQUEST_BODIES.website,
  },
  leaders: {
    id: 'leaders',
    title: 'Find the leaders',
    api: 'FindAll',
    facts: [
      { label: 'API', value: 'FindAll' },
      { label: 'Generator', value: 'preview' },
      { label: 'Cost', value: '$0.10' },
      { label: 'Latency', value: '~2 min' },
    ],
    request: REQUEST_BODIES.leaders,
  },
  company: {
    id: 'company',
    title: 'Research the company',
    api: 'Task',
    facts: [
      { label: 'API', value: 'Task' },
      { label: 'Processor', value: 'core' },
      { label: 'Cost', value: '$0.025' },
      { label: 'Latency', value: '~3 min' },
    ],
    request: REQUEST_BODIES.company,
  },
  team: {
    id: 'team',
    title: 'Tally the rest of the team',
    api: 'Task',
    facts: [
      { label: 'API', value: 'Task' },
      { label: 'Processor', value: 'pro' },
      { label: 'Cost', value: '$0.10' },
      { label: 'Latency', value: '~3 min' },
    ],
    request: REQUEST_BODIES.team,
  },
  leaderResearch: {
    id: 'leaderResearch',
    title: 'Research each leader',
    api: 'Task Group',
    facts: [
      { label: 'API', value: 'Task Group' },
      { label: 'Processor', value: 'base' },
      { label: 'Cost', value: '$0.01 / leader' },
      { label: 'Latency', value: '~2 min' },
    ],
    request: REQUEST_BODIES.leaderResearch,
  },
};

export const SCORE_STEP = {
  title: 'Score and post the card',
  api: 'No API call',
  facts: [
    { label: 'API', value: 'None' },
    { label: 'Cost', value: '$0' },
    { label: 'Latency', value: 'Instant' },
  ] satisfies StepFact[],
};

export function stepTitle(id: StepId): string {
  return id === 'score' ? SCORE_STEP.title : API_STEPS[id].title;
}

/** One billed step in the per-company cost; its color ties the bar to the legend. */
export interface CostRow {
  step: string;
  detail: string;
  usd: number;
  color: string;
}

/** What one company costs to research, most expensive step first (about 5 leaders). */
export const COST_PER_COMPANY: CostRow[] = [
  { step: 'Find the leaders', detail: 'FindAll preview', usd: 0.1, color: '#3b5bdb' },
  { step: 'Tally the rest of the team', detail: 'Task pro', usd: 0.1, color: '#2f9e44' },
  {
    step: 'Research each leader',
    detail: 'Task Group base, ~5 × $0.01',
    usd: 0.05,
    color: '#e8590c',
  },
  { step: 'Research the company', detail: 'Task core', usd: 0.025, color: '#9c36b5' },
  { step: 'Find the website', detail: 'Search advanced', usd: 0.005, color: '#868e96' },
];

/** Three Monitors at $0.01 a day each. */
export const MONITORS_PER_DAY_USD = 0.03;
/** The daily run researches at most this many new companies. */
export const COMPANIES_PER_DAY = 3;

/**
 * The same Raindrop card, researched by a Claude Opus 5.5 agent with web search and web
 * fetch instead of Parallel (measured 2026-10-08, priced at the Opus 5.5 API rates).
 */
export const OPUS_AGENT = {
  usdPerCompany: 1.9,
  searches: 23,
  fetches: 36,
  color: '#e8590c',
};

/** The Parallel bar beside the Opus agent's: the cost bar's first colour. */
export const PARALLEL_COLOR = '#3b5bdb';

/** "$0.10", "$0.025", "$0.005": whole cents when exact, else to a tenth of a cent. */
export function formatUsd(usd: number): string {
  const cents = usd * 100;
  return `$${usd.toFixed(Math.abs(cents - Math.round(cents)) < 1e-9 ? 2 : 3)}`;
}
