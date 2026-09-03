import type { JSONSchema7Definition } from 'json-schema';
import {
  resetRecentJobsFilters,
  setRecentJobsCategory,
  setRecentJobsCompany,
  setRecentJobsEmploymentType,
  setRecentJobsLevel,
  setRecentJobsLocation,
  setRecentJobsSearchTags,
  setRecentJobsSoftwareOnly,
  setRecentJobsTimeWindow,
} from '../../features/filters/slices/recentJobsFiltersSlice';
import type { ToolCtx, WebMcpToolDef } from '../types';
import {
  asString,
  buildSearchTags,
  err,
  navigateTo,
  ok,
  parseRecentArgs,
  resolveCompany,
  TIME_WINDOW_ENUM,
} from './shared';

/** Property set shared with `search_jobs`, minus the query-only cursor/limit. */
const ARRANGE_PROPERTIES: Record<string, JSONSchema7Definition> = {
  include: {
    type: 'array',
    items: { type: 'string' },
    description: 'Keyword must-match (OR within).',
  },
  exclude: { type: 'array', items: { type: 'string' }, description: 'Keyword must-not-match.' },
  category: {
    type: 'array',
    items: { type: 'string' },
    description: 'Enrichment category slugs (OR).',
  },
  level: {
    type: 'array',
    items: { type: 'string' },
    description: "Enrichment level slugs; 'entry' also matches new_grad.",
  },
  company: {
    type: 'array',
    items: { type: 'string' },
    description: 'Company id or display name.',
  },
  location: {
    type: 'array',
    items: { type: 'string' },
    description: 'Canonical location names from search_locations.',
  },
  timeWindow: { type: 'string', enum: [...TIME_WINDOW_ENUM], default: 'all' },
};

export function tier2DriveUi(ctx: ToolCtx): WebMcpToolDef[] {
  const apply_feed_filters: WebMcpToolDef = {
    name: 'apply_feed_filters',
    description:
      'Arrange the Recent Jobs feed: dispatch the recentJobsFilters setters for each provided field (omitted fields left untouched) and navigate to /; returns the resulting filter state.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: { ...ARRANGE_PROPERTIES },
    },
    annotations: { readOnlyHint: false },
    execute: async (rawArgs) => {
      const args = parseRecentArgs(rawArgs);
      const dispatch = ctx.store.dispatch;

      // Only touch the controls the caller actually named — additive, mirroring
      // the per-control UI. For a clean slate, call reset_feed_filters first.
      if ('timeWindow' in rawArgs) dispatch(setRecentJobsTimeWindow(args.timeWindow));
      if ('category' in rawArgs) dispatch(setRecentJobsCategory(args.category ?? []));
      if ('level' in rawArgs) dispatch(setRecentJobsLevel(args.level ?? []));
      if ('location' in rawArgs) dispatch(setRecentJobsLocation(args.location ?? []));
      if ('employmentType' in rawArgs) {
        dispatch(setRecentJobsEmploymentType(args.employmentType));
      }
      if ('softwareOnly' in rawArgs) {
        dispatch(setRecentJobsSoftwareOnly(Boolean(rawArgs.softwareOnly)));
      }
      if ('company' in rawArgs) {
        const ids = (args.company ?? [])
          .map(resolveCompany)
          .filter((id): id is string => id !== null);
        dispatch(setRecentJobsCompany(ids));
      }
      if ('include' in rawArgs || 'exclude' in rawArgs) {
        const tags = buildSearchTags(args.include, args.exclude);
        dispatch(setRecentJobsSearchTags(tags.length > 0 ? tags : undefined));
      }

      navigateTo(ctx, '/');
      return ok({ applied: ctx.store.getState().recentJobsFilters.filters });
    },
  };

  const reset_feed_filters: WebMcpToolDef = {
    name: 'reset_feed_filters',
    description:
      'Reset the Recent Jobs feed to its initial filter state (resetRecentJobsFilters) and navigate to /; returns the reset filter state.',
    inputSchema: { type: 'object', additionalProperties: false, properties: {} },
    annotations: { readOnlyHint: false },
    execute: async () => {
      ctx.store.dispatch(resetRecentJobsFilters());
      navigateTo(ctx, '/');
      return ok({ applied: ctx.store.getState().recentJobsFilters.filters });
    },
  };

  const open_job: WebMcpToolDef = {
    name: 'open_job',
    description:
      "Open a posting's apply URL in a new tab (window.open); returns { opened, url }. Popups are blocked without a user gesture — assert the intent, not a live navigation.",
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      required: ['url'],
      properties: {
        url: {
          type: 'string',
          format: 'uri',
          description: "A posting's apply URL (job.url from search_jobs / get_job).",
        },
      },
    },
    annotations: { readOnlyHint: false, openWorldHint: true },
    execute: async (rawArgs) => {
      const url = asString(rawArgs.url);
      if (!url) return err('open_job requires a string `url`.');
      window.open(url, '_blank', 'noopener');
      return ok({ opened: true, url });
    },
  };

  return [apply_feed_filters, reset_feed_filters, open_job];
}
