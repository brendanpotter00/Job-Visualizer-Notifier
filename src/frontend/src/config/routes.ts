/**
 * Application route definitions
 *
 * Centralized routing configuration for type safety and maintainability.
 */

import { CUSTOM_COMPANIES_CONFIG } from './customCompanies';

export const ROUTES = {
  RECENT_JOBS: '/',
  COMPANIES: '/companies',
  CURATED_COMPANIES: '/curated-companies',
  // Flag-gated (VITE_CUSTOM_COMPANIES_ENABLED). The path constant always
  // exists — App.tsx decides whether to register a route for it, and
  // PRIMARY_NAV_ITEMS decides whether to link to it.
  MY_COMPANIES: '/add-companies',
  // Private per-company trend page for a user-added company. Flag-gated exactly
  // like MY_COMPANIES; `:id` is a RUNTIME `u-…` id, never a compile-time
  // `COMPANY_IDS` member — the page fetches by id instead of the companies-page
  // selector chain. Build a concrete path with `buildMyCompanyDetailPath`.
  MY_COMPANY_DETAIL: '/add-companies/:id',
  // The pre-rename path, kept ONLY so links and open tabs from before the
  // "My Companies" → "Add Companies" rename keep working. App.tsx registers a
  // splat route on it that redirects to MY_COMPANIES, sub-path and query
  // included — the failure this prevents is a bookmarked
  // `/my-companies/u-abc123` turning into a blank 404 rather than that
  // company's trend page. Nothing links here; do not add a nav entry.
  MY_COMPANIES_LEGACY: '/my-companies',
  WHY: '/why',
  QA: '/qa',
  ACCOUNT: '/account',
  SAVED_FILTERS: '/saved-filters',
  VOTE_FEATURES: '/vote-features',
  ADMIN_USERS: '/admin/users',
  ADMIN_LOCATION_NORMALIZATION: '/admin/location-normalization',
  // Public route (not admin-gated). Admins still get a sidebar link via
  // ADMIN_NAV_ITEMS; everyone else reaches it from the Changelog card.
  LOCATION_PIPELINE: '/location-pipeline',
  ADMIN_ENRICHMENT: '/admin/enrichment',
  // Read-only oversight for user-added boards (E7). Behind `AdminRoute` only —
  // deliberately NOT gated on VITE_CUSTOM_COMPANIES_ENABLED, because the moment
  // you most want to inspect the feature is an environment where the
  // user-facing flag is off.
  ADMIN_CUSTOM_COMPANIES: '/admin/custom-companies',
  ADMIN_FEEDBACK: '/admin/feedback',
} as const;

/**
 * Concrete path to a user-company's private trend page. The single place that
 * knows how `MY_COMPANY_DETAIL`'s `:id` slot is filled, so links stay in sync
 * with the route pattern.
 */
export function buildMyCompanyDetailPath(id: string): string {
  return `/add-companies/${id}`;
}

/**
 * Every icon a sidebar entry may name.
 *
 * Lives here rather than in NavigationDrawer because it is half of a contract
 * with two ends: nav items pick a name, and the drawer's `iconMap` must supply
 * a component for it. Typing `NavItem.icon` as a bare `string` would break that
 * link — the drawer casts `item.icon as IconName`, so a typo'd name would pass
 * the compiler and then render `undefined`. Keeping the union here means a bad
 * name fails at the definition site, and `Record<NavIconName, …>` on the map
 * side makes a missing component fail too.
 */
export type NavIconName =
  | 'Schedule'
  | 'Info'
  | 'BugReport'
  | 'AccountCircle'
  | 'ThumbUp'
  | 'TrendingUp'
  | 'Business'
  | 'People'
  | 'Place'
  | 'AccountTree'
  | 'AutoAwesome'
  | 'Feedback'
  | 'FilterListAlt'
  | 'AddBusiness'
  | 'Construction';

/**
 * Shape of a sidebar entry.
 *
 * Introduced so `PRIMARY_NAV_ITEMS` can vary with a feature flag. Every item
 * literal below stays `as const`, so nothing loses its narrow types at the
 * definition site; only the exported *array* is widened to this contract,
 * because a flag-dependent tuple would be a union of two tuple types and
 * `.map()` is not callable on such a union. The other nav groups are
 * untouched and keep their `as const` tuple types.
 */
export interface NavItem {
  readonly path: string;
  readonly label: string;
  readonly icon: NavIconName;
  /**
   * Renders a `BetaBadge` chip after the label in the sidebar. A flag rather
   * than free text on purpose — the marker is the same everywhere it appears,
   * and a `badge: string` would invite a second, differently-worded one.
   */
  readonly beta?: boolean;
}

const PRIMARY_NAV_BASE = [
  {
    path: ROUTES.RECENT_JOBS,
    label: 'Recent Job Postings',
    icon: 'Schedule',
  },
  {
    path: ROUTES.COMPANIES,
    label: 'Company Hiring Trends',
    icon: 'TrendingUp',
  },
  {
    path: ROUTES.SAVED_FILTERS,
    label: 'Saved Filters',
    icon: 'FilterListAlt',
  },
] as const;

/**
 * Appended to the primary nav only while `VITE_CUSTOM_COMPANIES_ENABLED` is on.
 * With the flag off there is no nav entry and no route (see App.tsx), so the
 * sidebar is identical to what it was before the feature existed.
 */
const MY_COMPANIES_NAV_ITEM = {
  path: ROUTES.MY_COMPANIES,
  // The beta marker is a BADGE, not part of the label — the label used to read
  // "Add Companies (beta)" and the parenthesised word had to be carried by every
  // consumer of `label` (tooltip, tests, any future search). Keeping the label
  // the page's actual name and the status a separate flag means the drawer
  // decides how the marker looks, and nothing else has to know about it.
  label: 'Add Companies',
  icon: 'AddBusiness',
  beta: true,
} as const;

/**
 * Functional tabs — the core app features. Rendered above the "INFO" divider
 * in the sidebar.
 */
export const PRIMARY_NAV_ITEMS: readonly NavItem[] = CUSTOM_COMPANIES_CONFIG.isEnabled
  ? [...PRIMARY_NAV_BASE, MY_COMPANIES_NAV_ITEM]
  : PRIMARY_NAV_BASE;

/**
 * Info tabs — supplementary / informational pages. Rendered below the "INFO"
 * divider in the sidebar, mirroring the ADMIN group's divider + caption.
 */
export const INFO_NAV_ITEMS = [
  {
    path: ROUTES.CURATED_COMPANIES,
    label: 'Curated Companies',
    icon: 'Business',
  },
  {
    path: ROUTES.VOTE_FEATURES,
    label: 'Give Feedback',
    icon: 'ThumbUp',
  },
  {
    path: ROUTES.WHY,
    label: 'Why This Was Built',
    icon: 'Info',
  },
] as const;

/**
 * Combined customer-facing nav items (functional + info), in display order.
 * Retained for incidental consumers that iterate the full non-admin sidebar.
 */
export const USER_NAV_ITEMS: readonly NavItem[] = [...PRIMARY_NAV_ITEMS, ...INFO_NAV_ITEMS];

export const ADMIN_NAV_ITEMS = [
  {
    path: ROUTES.ADMIN_USERS,
    label: 'Users',
    icon: 'People',
  },
  {
    path: ROUTES.ADMIN_LOCATION_NORMALIZATION,
    label: 'Location Normalization',
    icon: 'Place',
  },
  {
    path: ROUTES.LOCATION_PIPELINE,
    label: 'Location Pipeline',
    icon: 'AccountTree',
  },
  {
    path: ROUTES.ADMIN_ENRICHMENT,
    label: 'Enrichment Pipeline',
    icon: 'AutoAwesome',
  },
  {
    path: ROUTES.QA,
    label: 'Scraper Runs',
    icon: 'BugReport',
  },
  // Scraper-adjacent, so it sits with the scraper entry rather than with the
  // user-facing ones.
  {
    path: ROUTES.ADMIN_CUSTOM_COMPANIES,
    label: 'Custom Companies',
    icon: 'Construction',
  },
  {
    path: ROUTES.ADMIN_FEEDBACK,
    label: 'User Feedback',
    icon: 'Feedback',
  },
] as const;

/**
 * Legacy combined export — non-admin items only. Kept for any incidental
 * consumer that iterates the full sidebar; admin items must come from
 * ADMIN_NAV_ITEMS and be gated on `user.isAdmin`.
 */
export const NAV_ITEMS = USER_NAV_ITEMS;
