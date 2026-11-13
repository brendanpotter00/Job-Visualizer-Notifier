import { describe, it, expect, vi } from 'vitest';
import { createTestStore } from '../../test/testUtils';
import { ROUTES } from '../../config/routes';
import { tier2DriveUi } from '../../webmcp/tools/tier2DriveUi';
import type { AppStore, NavigateFn } from '../../webmcp/types';

function feedTool(name: string, navigate: NavigateFn) {
  const tools = tier2DriveUi({
    store: createTestStore() as unknown as AppStore,
    getNavigate: () => navigate,
    getLogin: () => null,
  });
  const tool = tools.find((candidate) => candidate.name === name);
  if (!tool) throw new Error(`missing tool ${name}`);
  return tool;
}

describe('WebMCP feed tools', () => {
  it.each(['apply_feed_filters', 'reset_feed_filters'])(
    '%s navigates to the jobs board, not the landing page at /',
    async (name) => {
      const navigate = vi.fn() as unknown as NavigateFn;
      await feedTool(name, navigate).execute({});
      expect(navigate).toHaveBeenCalledWith(ROUTES.RECENT_JOBS);
      expect(navigate).not.toHaveBeenCalledWith(ROUTES.HOME);
    }
  );
});
