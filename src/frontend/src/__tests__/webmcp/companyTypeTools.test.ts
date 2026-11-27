import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createTestStore } from '../../test/testUtils';
import { jobsApi } from '../../features/jobs/jobsApi';
import { savedFiltersApi } from '../../features/savedFilters/savedFiltersApi';
import { FALLBACK_COMPANY_CATEGORY_OPTIONS } from '../../config/companyCategories';
import { tier1Read } from '../../webmcp/tools/tier1Read';
import { tier2DriveUi } from '../../webmcp/tools/tier2DriveUi';
import { tier3Auth } from '../../webmcp/tools/tier3Auth';
import type { AppStore, ToolCtx, WebMcpToolDef } from '../../webmcp/types';

vi.mock('../../features/features/getTokenOrNull', () => ({
  getTokenOrNull: vi.fn(async () => 'test-token'),
}));

/** The WebMCP tools learn the Recent page's company type filter. */
function makeCtx() {
  const store = createTestStore() as unknown as AppStore;
  const navigate = vi.fn();
  const ctx: ToolCtx = { store, getNavigate: () => navigate, getLogin: () => null };
  return { ctx, store, navigate };
}

function tool(tools: WebMcpToolDef[], name: string): WebMcpToolDef {
  const found = tools.find((t) => t.name === name);
  if (!found) throw new Error(`test setup: no ${name} tool`);
  return found;
}

const BASE_FACETS = {
  categories: [{ slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0 }],
  levels: [{ slug: 'senior', label: 'Senior', sortOrder: 0, parentSlug: null }],
  subcategories: [],
};

describe('list_filter_options', () => {
  it('returns the served company types', async () => {
    const { ctx, store } = makeCtx();
    const served = [{ slug: 'fintech', label: 'Fintech & Trading', sortOrder: 0, parentSlug: null }];
    await store.dispatch(
      jobsApi.util.upsertQueryData('getFacets', undefined, {
        ...BASE_FACETS,
        companyCategories: served,
      })
    );
    const res = await tool(tier1Read(ctx), 'list_filter_options').execute({});
    expect(res.isError).toBe(false);
    expect((res.structuredContent as { companyCategories: unknown }).companyCategories).toEqual(
      served
    );
  });

  it('falls back to the bundled list when the backend sends none', async () => {
    const { ctx, store } = makeCtx();
    await store.dispatch(jobsApi.util.upsertQueryData('getFacets', undefined, BASE_FACETS));
    const res = await tool(tier1Read(ctx), 'list_filter_options').execute({});
    expect((res.structuredContent as { companyCategories: unknown }).companyCategories).toEqual([
      ...FALLBACK_COMPANY_CATEGORY_OPTIONS,
    ]);
  });
});

describe('search_jobs companyCategory', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(new Response('{}', { status: 500 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends company_category as repeated params, sorted', async () => {
    const { ctx } = makeCtx();
    await tool(tier1Read(ctx), 'search_jobs').execute({ companyCategory: ['fintech', 'big_tech'] });
    const url = String(fetchMock.mock.calls[0][0]);
    expect(new URLSearchParams(url.split('?')[1]).getAll('company_category')).toEqual([
      'big_tech',
      'fintech',
    ]);
  });

  it('omits it when not given', async () => {
    const { ctx } = makeCtx();
    await tool(tier1Read(ctx), 'search_jobs').execute({});
    const url = String(fetchMock.mock.calls[0][0]);
    expect(new URLSearchParams(url.split('?')[1]).has('company_category')).toBe(false);
  });
});

describe('apply_feed_filters companyCategory', () => {
  it('sets the Recent company type and navigates to /jobs', async () => {
    const { ctx, store, navigate } = makeCtx();
    const res = await tool(tier2DriveUi(ctx), 'apply_feed_filters').execute({
      companyCategory: ['ai_labs'],
    });
    expect(res.isError).toBe(false);
    expect(store.getState().recentJobsFilters.filters.companyCategory).toEqual(['ai_labs']);
    expect(navigate).toHaveBeenCalledWith('/jobs');
  });

  it('[] clears it; leaving it out leaves it alone', async () => {
    const { ctx, store } = makeCtx();
    const apply = tool(tier2DriveUi(ctx), 'apply_feed_filters');
    await apply.execute({ companyCategory: ['ai_labs'] });
    await apply.execute({ include: ['rust'] });
    expect(store.getState().recentJobsFilters.filters.companyCategory).toEqual(['ai_labs']);
    await apply.execute({ companyCategory: [] });
    expect(store.getState().recentJobsFilters.filters.companyCategory).toBeUndefined();
  });
});

describe('save_filter_defaults companyCategory', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function spyOnPut() {
    return vi
      .spyOn(savedFiltersApi.endpoints.updateSavedFilters, 'initiate')
      .mockImplementation(((body: unknown) => () => ({
        unwrap: () => Promise.resolve(body),
        reset: () => {},
      })) as unknown as typeof savedFiltersApi.endpoints.updateSavedFilters.initiate);
  }

  it('sends companyCategory when the caller passes it', async () => {
    const put = spyOnPut();
    const { ctx } = makeCtx();
    const res = await tool(tier3Auth(ctx), 'save_filter_defaults').execute({
      companyCategory: ['big_tech'],
    });
    expect(res.isError).toBe(false);
    expect(put.mock.calls[0][0]).toMatchObject({ companyCategory: ['big_tech'] });
  });

  it('sends [] for an explicit empty list (clear)', async () => {
    const put = spyOnPut();
    const { ctx } = makeCtx();
    await tool(tier3Auth(ctx), 'save_filter_defaults').execute({ companyCategory: [] });
    expect(put.mock.calls[0][0]).toMatchObject({ companyCategory: [] });
  });

  it('omits the key when the caller does not pass it (the backend keeps the stored value)', async () => {
    const put = spyOnPut();
    const { ctx } = makeCtx();
    await tool(tier3Auth(ctx), 'save_filter_defaults').execute({ level: ['senior'] });
    expect(put.mock.calls[0][0]).not.toHaveProperty('companyCategory');
  });
});
