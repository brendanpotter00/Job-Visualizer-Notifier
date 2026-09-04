import { describe, it, expect } from 'vitest';
import {
  ROUTES,
  NAV_ITEMS,
  ADMIN_NAV_ITEMS,
  PRIMARY_NAV_ITEMS,
  INFO_NAV_ITEMS,
  USER_NAV_ITEMS,
} from '../../config/routes';

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

    // The landing page replaced the four-tab prototype workspace on 2026-09-03
    // and moved off /admin/…, which is the part with a deployment consequence:
    // /admin/:path(.*) already rewrote to index.html in vercel.json, and /landing
    // does not, so it needs its own rewrite or a hard refresh 404s.
    it('exposes the LANDING path at /landing, outside the /admin prefix', () => {
      expect(ROUTES.LANDING).toBe('/landing');
      expect(ROUTES.LANDING.startsWith('/admin')).toBe(false);
    });

    it('keeps the pre-consolidation landing path as a legacy alias only', () => {
      // Not a free-floating string: App.tsx builds the redirect route from it.
      expect(ROUTES.LANDING_LEGACY).toBe('/admin/landing-prototypes');
      expect(ROUTES.LANDING_LEGACY).not.toBe(ROUTES.LANDING);
    });
  });

  // The landing page is UNLISTED by owner decision: reachable by direct URL
  // only, so reviewers can open it without signing in and nobody stumbles into
  // it from the sidebar. A nav entry is the one change that would silently
  // undo that, so every nav array is checked rather than just the combined one.
  describe('the landing page stays unlisted', () => {
    it('appears in no nav array, new path or legacy', () => {
      const navGroups = {
        PRIMARY_NAV_ITEMS,
        INFO_NAV_ITEMS,
        USER_NAV_ITEMS,
        NAV_ITEMS,
        ADMIN_NAV_ITEMS,
      };
      for (const [name, group] of Object.entries(navGroups)) {
        const paths = group.map((item) => item.path);
        expect(paths, `${name} must not link the landing page`).not.toContain(ROUTES.LANDING);
        expect(paths, `${name} must not link the legacy landing path`).not.toContain(
          ROUTES.LANDING_LEGACY
        );
      }
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

    it('includes a "Custom Companies" item between "Scraper Runs" and "User Feedback"', () => {
      const labels = ADMIN_NAV_ITEMS.map((i) => i.label);
      const item = ADMIN_NAV_ITEMS.find((i) => i.path === ROUTES.ADMIN_CUSTOM_COMPANIES);
      expect(item).toBeDefined();
      expect(item?.label).toBe('Custom Companies');
      expect(item?.icon).toBe('Construction');
      expect(labels.indexOf('Custom Companies')).toBe(labels.indexOf('Scraper Runs') + 1);
      expect(labels.indexOf('Custom Companies')).toBe(labels.indexOf('User Feedback') - 1);
    });

    it('every ADMIN_NAV_ITEMS path matches a ROUTES value', () => {
      const routeValues = new Set<string>(Object.values(ROUTES));
      for (const item of ADMIN_NAV_ITEMS) {
        expect(routeValues.has(item.path)).toBe(true);
      }
    });
  });
});
