import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createTestStore } from '../../test/testUtils';
import { tier1Read } from '../../webmcp/tools/tier1Read';
import { tier2DriveUi } from '../../webmcp/tools/tier2DriveUi';
import type { AppStore, ToolCtx, WebMcpToolDef } from '../../webmcp/types';

/**
 * The Recent feed lost its company filter on 2026-11-12. These pin the two
 * WebMCP consequences: the UI-driving tool refuses a `company` argument (the shim
 * runs no schema validator, so without the guard it would be silently dropped),
 * and the read tool still scopes by company — now through the builder's company
 * scope instead of a slice field that no longer exists.
 */

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

describe('apply_feed_filters', () => {
  it('rejects a company argument instead of silently ignoring it', async () => {
    const { ctx, store, navigate } = makeCtx();
    const before = store.getState().recentJobsFilters.filters;

    const res = await tool(tier2DriveUi(ctx), 'apply_feed_filters').execute({
      company: ['apple'],
      include: ['rust'],
    });

    expect(res.isError).toBe(true);
    expect(JSON.stringify(res.structuredContent)).toContain('search_jobs');
    // Nothing applied and no navigation: a rejected call must not half-apply.
    expect(store.getState().recentJobsFilters.filters).toBe(before);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('still applies the filters the feed does have', async () => {
    const { ctx, store, navigate } = makeCtx();

    const res = await tool(tier2DriveUi(ctx), 'apply_feed_filters').execute({ include: ['rust'] });

    expect(res.isError).toBe(false);
    expect(store.getState().recentJobsFilters.filters.searchTags).toEqual([
      { text: 'rust', mode: 'include' },
    ]);
    expect(navigate).toHaveBeenCalledWith('/');
  });
});

describe('search_jobs company scope', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    // The request URL is the assertion; the response only has to end the call.
    fetchMock.mockResolvedValue(new Response('{}', { status: 500 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function requestedParams(args: Record<string, unknown>): Promise<URLSearchParams> {
    const { ctx } = makeCtx();
    await tool(tier1Read(ctx), 'search_jobs').execute(args);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = String(fetchMock.mock.calls[0][0]);
    return new URLSearchParams(url.split('?')[1]);
  }

  it('sends resolved company ids (by id or display name), sorted, dropping unknown tokens', async () => {
    const params = await requestedParams({ company: ['stripe', 'Apple', 'no-such-company'] });

    expect(params.getAll('company')).toEqual(['apple', 'stripe']);
  });

  it('omits the company param when no company is given, or none resolves', async () => {
    expect((await requestedParams({})).getAll('company')).toEqual([]);
    fetchMock.mockClear();
    expect((await requestedParams({ company: ['no-such-company'] })).getAll('company')).toEqual([]);
  });
});
