// Content for the public "How Launch Radar works" page. Each request body is an
// abridged copy of what scripts/launch_radar/ sends to the Parallel API: long
// descriptions end in "…", and output schemas are shown as their field names.
// Prices and latencies are the ones recorded in docs/implementations/launch-radar/.

/** An output schema shown as a comment that lists its fields, not as full JSON Schema. */
export class SchemaFields {
  readonly fields: readonly string[];
  constructor(...fields: string[]) {
    this.fields = fields;
  }
}

export type RequestValue =
  | string
  | number
  | boolean
  | null
  | SchemaFields
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

const EVENT_FIELDS = new SchemaFields(
  'company_name',
  'company_domain',
  'event_type',
  'round',
  'amount_usd',
  'investors',
  'announced_at',
  'source_url',
  'headline'
);

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
    request: {
      type: 'event_stream',
      frequency: '1d',
      processor: 'base',
      settings: {
        query:
          'Startups announcing a newly closed Series A, Series B or later venture funding round, as reported in press releases or tech/business news. One specific company per event.',
        include_backfill: true,
        output_schema: { type: 'json', json_schema: EVENT_FIELDS },
      },
    },
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
    request: {
      objective:
        'FindAll early-stage startups that publicly announced a newly closed pre-seed, seed, Series A or Series B funding round, or a notable new product launch, between 2026-09-07 and 2026-10-07 (inclusive).',
      entity_type: 'companies',
      match_conditions: [
        {
          name: 'early_stage_startup_check',
          description:
            'The company is an independent, privately held early-stage startup (roughly pre-seed to Series B). It is NOT a large or established technology company, NOT publicly traded, and NOT a subsidiary. …',
        },
        {
          name: 'recent_announcement_check',
          description:
            'The company publicly announced, between 2026-09-07 and 2026-10-07, EITHER a newly closed pre-seed–Series B round OR a notable new product launch. The announcement itself must be dated in that window. …',
        },
      ],
      generator: 'base',
      match_limit: 20,
    },
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
    request: {
      processor: 'base',
      output_schema: { type: 'json', json_schema: EVENT_FIELDS },
    },
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
    request: {
      objective:
        'The official company website (homepage) of the startup finmid. Context: finmid raises EUR 17M Series A extension',
      search_queries: ['finmid official website', 'finmid startup'],
      mode: 'advanced',
      advanced_settings: { max_results: 8 },
    },
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
    request: {
      objective:
        'Find the founders and current senior leadership team (CEO, CTO, other C-level executives, VPs and Heads of functions) of Raindrop AI, the company whose website is raindrop.ai.',
      entity_type: 'people',
      match_conditions: [
        {
          name: 'current_leader_at_company',
          description:
            'The person is a founder/co-founder of Raindrop AI (raindrop.ai) or currently holds a C-level, VP-level or Head-of role there. It must be this exact company, not one with a similar name. …',
        },
      ],
      generator: 'preview',
      match_limit: 8,
    },
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
    request: {
      input: {
        company_name: 'Raindrop AI',
        company_domain: 'raindrop.ai',
        context: 'Raindrop AI announced a $35M Series A',
      },
      processor: 'core',
      task_spec: {
        output_schema: {
          type: 'json',
          json_schema: new SchemaFields(
            'one_liner',
            'website_url',
            'what_they_do',
            'latest_round',
            'prior_rounds',
            'total_raised_usd',
            'latest_announcement',
            'notable_facts',
            'blurb',
            'careers_url',
            'ats',
            'founders'
          ),
        },
      },
    },
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
    request: {
      input:
        'Company: Raindrop AI (raindrop.ai). Find current employees of this exact company who are NOT its founders, co-founders or C-level executives. Use public profiles (LinkedIn, team pages, personal sites). For the people you find, tally the universities they attended and their notable previous employers. Count each person once per school and per employer. Do not guess: only count facts you found.',
      processor: 'pro',
      task_spec: {
        output_schema: {
          type: 'json',
          json_schema: new SchemaFields(
            'profiles_found',
            'team_size_estimate',
            'schools',
            'prior_employers',
            'sample_names'
          ),
        },
      },
    },
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
    request: {
      inputs: [
        {
          input: {
            person_name: 'Zubin Singh Koticha',
            current_title: 'CEO and Co-Founder',
            linkedin_url: null,
            company_name: 'Raindrop AI',
            company_domain: 'raindrop.ai',
          },
          processor: 'base',
        },
      ],
      default_task_spec: {
        output_schema: {
          type: 'json',
          json_schema: new SchemaFields(
            'current_title',
            'linkedin_url',
            'education',
            'prior_roles',
            'founded_before',
            'years_experience',
            'industry_experience_summary',
            'notable_signals'
          ),
        },
      },
    },
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
