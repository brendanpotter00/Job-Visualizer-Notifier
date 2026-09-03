import type { SavedFilters } from '../../types';
import { getTokenOrNull } from '../../features/features/getTokenOrNull';
import { updateEnabledCompanies } from '../../features/auth/authService';
import { loadEnabledCompanies } from '../../features/preferences/enabledCompaniesSlice';
import { savedFiltersApi } from '../../features/savedFilters/savedFiltersApi';
import { featuresApi } from '../../features/features/featuresApi';
import { FEEDBACK_MAX_LENGTH, feedbackApi } from '../../features/feedback/feedbackApi';
import { logger } from '../../lib/logger';
import type { ToolCtx, WebMcpToolDef } from '../types';
import {
  asBool,
  asString,
  asStringArray,
  asTimeWindow,
  err,
  ok,
  runMutation,
  TIME_WINDOW_ENUM,
} from './shared';

export function tier3Auth(ctx: ToolCtx): WebMcpToolDef[] {
  const request_sign_in: WebMcpToolDef = {
    name: 'request_sign_in',
    description:
      'Trigger the sign-in prompt (useAuth().login / Auth0 redirect). No token ever reaches the agent; returns { prompted }. Cannot complete headlessly — Tier-3 tests authenticate via the harness fixture.',
    inputSchema: { type: 'object', additionalProperties: false, properties: {} },
    annotations: { readOnlyHint: false },
    execute: async () => {
      const login = ctx.getLogin();
      if (!login) {
        return err('Sign-in unavailable: the WebMCP auth bridge is not mounted.');
      }
      // Fire-and-forget: loginWithRedirect navigates away and cannot resolve in
      // this call; the contract is only that the prompt path fires.
      void login().catch(() => {
        /* swallow redirect / popup-blocker errors — smoke-only path */
      });
      return ok({ prompted: true });
    },
  };

  const set_enabled_companies: WebMcpToolDef = {
    name: 'set_enabled_companies',
    description:
      'Set the signed-in user’s enabled companies (PUT /api/users/enabled-companies) and refresh the store; returns the server echo { companyIds, autoEnroll }. Requires sign-in.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      required: ['companyIds'],
      properties: {
        companyIds: { type: 'array', items: { type: 'string' } },
        autoEnroll: { type: 'boolean', default: true },
      },
    },
    annotations: { readOnlyHint: false },
    execute: async (rawArgs) => {
      const companyIds = asStringArray(rawArgs.companyIds) ?? [];
      const autoEnroll = asBool(rawArgs.autoEnroll) ?? true;
      const token = await getTokenOrNull();
      if (!token) return err('Sign in required');

      const echo = await updateEnabledCompanies(token, companyIds, autoEnroll);
      // Refresh the store so selectors see the new set. Best-effort: the DB
      // write (the asserted side effect) already succeeded above.
      try {
        await ctx.store.dispatch(loadEnabledCompanies(token)).unwrap();
      } catch (e) {
        logger.warn('[webmcp] set_enabled_companies store refresh failed:', e);
      }
      return ok({ companyIds: echo.companyIds, autoEnroll: echo.autoEnroll });
    },
  };

  const save_filter_defaults: WebMcpToolDef = {
    name: 'save_filter_defaults',
    description:
      'Save the signed-in user’s default filters (PUT /api/users/saved-filters): time windows, locations, category/level, active keyword-list pointers; returns the server echo. Requires sign-in.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        recentTimeWindow: { type: 'string', enum: [...TIME_WINDOW_ENUM] },
        trendTimeWindow: { type: 'string', enum: [...TIME_WINDOW_ENUM] },
        locations: { type: 'array', items: { type: 'string' } },
        category: { type: 'array', items: { type: 'string' } },
        level: { type: 'array', items: { type: 'string' } },
        recentActiveKeywordListId: { type: ['string', 'null'] },
        trendActiveKeywordListId: { type: ['string', 'null'] },
      },
    },
    annotations: { readOnlyHint: false },
    execute: async (rawArgs) => {
      const token = await getTokenOrNull();
      if (!token) return err('Sign in required');

      const body: SavedFilters = {
        recentTimeWindow: asTimeWindow(rawArgs.recentTimeWindow, 'all'),
        trendTimeWindow: asTimeWindow(rawArgs.trendTimeWindow, '90d'),
        locations: asStringArray(rawArgs.locations) ?? [],
        category: asStringArray(rawArgs.category) ?? [],
        level: asStringArray(rawArgs.level) ?? [],
        recentActiveKeywordListId: asString(rawArgs.recentActiveKeywordListId) ?? null,
        trendActiveKeywordListId: asString(rawArgs.trendActiveKeywordListId) ?? null,
      };

      const saved = await runMutation(
        ctx.store.dispatch(savedFiltersApi.endpoints.updateSavedFilters.initiate(body))
      );
      return ok(saved);
    },
  };

  const upvote_feature: WebMcpToolDef = {
    name: 'upvote_feature',
    description:
      'Upvote a feature (POST /api/features/{id}/upvote); returns { featureId, upvoteCount, hasUpvoted }. Requires sign-in.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      required: ['featureId'],
      properties: { featureId: { type: 'string' } },
    },
    annotations: { readOnlyHint: false },
    execute: async (rawArgs) => {
      const featureId = asString(rawArgs.featureId);
      if (!featureId) return err('upvote_feature requires a string `featureId`.');
      try {
        const result = await runMutation(
          ctx.store.dispatch(featuresApi.endpoints.upvoteFeature.initiate(featureId))
        );
        return ok({
          featureId: result.featureId,
          upvoteCount: result.upvoteCount,
          hasUpvoted: result.hasUpvoted,
        });
      } catch (e) {
        return err(`upvote_feature failed: ${e instanceof Error ? e.message : 'unknown error'}`);
      }
    },
  };

  const submit_feedback: WebMcpToolDef = {
    name: 'submit_feedback',
    description:
      'Submit user feedback (POST /api/feedback); stores anonymously when signed-out. Returns { submitted }.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      required: ['message'],
      properties: {
        message: { type: 'string', minLength: 1, maxLength: FEEDBACK_MAX_LENGTH },
      },
    },
    annotations: { readOnlyHint: false },
    execute: async (rawArgs) => {
      const message = asString(rawArgs.message);
      if (!message || message.length === 0) {
        return err('submit_feedback requires a non-empty `message`.');
      }
      if (message.length > FEEDBACK_MAX_LENGTH) {
        return err(`message exceeds the ${FEEDBACK_MAX_LENGTH}-character limit.`);
      }
      try {
        await runMutation(
          ctx.store.dispatch(feedbackApi.endpoints.submitFeedback.initiate({ message }))
        );
        return ok({ submitted: true });
      } catch (e) {
        return err(`submit_feedback failed: ${e instanceof Error ? e.message : 'unknown error'}`);
      }
    },
  };

  return [
    request_sign_in,
    set_enabled_companies,
    save_filter_defaults,
    upvote_feature,
    submit_feedback,
  ];
}
