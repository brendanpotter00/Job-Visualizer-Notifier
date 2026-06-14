import { describe, it, expect } from 'vitest';
import { ROUTES, NAV_ITEMS, ADMIN_NAV_ITEMS } from '../../config/routes';

describe('routes config', () => {
  describe('ROUTES', () => {
    it('exposes the VOTE_FEATURES path at /vote-features', () => {
      expect(ROUTES.VOTE_FEATURES).toBe('/vote-features');
    });

    it('keeps existing routes stable', () => {
      expect(ROUTES.RECENT_JOBS).toBe('/');
      expect(ROUTES.COMPANIES).toBe('/companies');
      expect(ROUTES.WHY).toBe('/why');
      expect(ROUTES.QA).toBe('/qa');
      expect(ROUTES.ACCOUNT).toBe('/account');
    });

    it('exposes the ADMIN_FEEDBACK path at /admin/feedback', () => {
      expect(ROUTES.ADMIN_FEEDBACK).toBe('/admin/feedback');
    });

    it('contains no duplicate paths', () => {
      const paths = Object.values(ROUTES);
      expect(new Set(paths).size).toBe(paths.length);
    });
  });

  describe('NAV_ITEMS', () => {
    it('includes a "Give Feedback" item wired to ROUTES.VOTE_FEATURES with the ThumbUp icon', () => {
      const voteItem = NAV_ITEMS.find((item) => item.path === ROUTES.VOTE_FEATURES);
      expect(voteItem).toBeDefined();
      expect(voteItem?.label).toBe('Give Feedback');
      expect(voteItem?.icon).toBe('ThumbUp');
    });

    it('every NAV_ITEMS path matches a ROUTES value', () => {
      const routeValues = new Set<string>(Object.values(ROUTES));
      for (const item of NAV_ITEMS) {
        expect(routeValues.has(item.path)).toBe(true);
      }
    });

    it('NAV_ITEMS paths are unique', () => {
      const paths = NAV_ITEMS.map((item) => item.path);
      expect(new Set(paths).size).toBe(paths.length);
    });
  });

  describe('ADMIN_NAV_ITEMS', () => {
    it('includes a "User Feedback" item wired to ROUTES.ADMIN_FEEDBACK with the Feedback icon', () => {
      const item = ADMIN_NAV_ITEMS.find((i) => i.path === ROUTES.ADMIN_FEEDBACK);
      expect(item).toBeDefined();
      expect(item?.label).toBe('User Feedback');
      expect(item?.icon).toBe('Feedback');
    });

    it('every ADMIN_NAV_ITEMS path matches a ROUTES value', () => {
      const routeValues = new Set<string>(Object.values(ROUTES));
      for (const item of ADMIN_NAV_ITEMS) {
        expect(routeValues.has(item.path)).toBe(true);
      }
    });
  });
});
