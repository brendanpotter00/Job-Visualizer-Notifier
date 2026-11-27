import { ROUTES } from '../../config/routes';
import { SUBCATEGORY_PARENT_SLUG } from '../../constants/enrichment';
import type {
  CompleteOnboardingArgs,
  OnboardingAnswers,
} from '../../features/savedFilters/savedFiltersApi';
import type { SavedFilters } from '../../types';

/**
 * The first-sign-in questions: what they ask, in what order, and the small
 * pure rules around the answers. The components render these; nothing here
 * touches React or the store, so the rules are unit-testable on their own.
 * Plan: `docs/implementations/onboardingFlow/plan.html`.
 */

export const ONBOARDING_STEP_COUNT = 4;
export type OnboardingStep = 0 | 1 | 2 | 3;

export interface OnboardingQuestion {
  /** The h1 of the step. There is no subtitle under it. */
  title: string;
  /** The step's short name, for `document.title`. */
  shortName: string;
}

export const ONBOARDING_QUESTIONS: readonly OnboardingQuestion[] = [
  { title: 'What roles are you looking for?', shortName: 'Roles' },
  { title: 'Which levels fit you?', shortName: 'Levels' },
  { title: 'Where do you want to work?', shortName: 'Places' },
  { title: 'What kinds of companies do you want?', shortName: 'Companies' },
];

/** `document.title` while a step is on screen. */
export function onboardingDocumentTitle(step: OnboardingStep, appTitle: string): string {
  return `Question ${step + 1} of ${ONBOARDING_STEP_COUNT}: ${ONBOARDING_QUESTIONS[step].shortName} | ${appTitle}`;
}

/**
 * The Location filter's whole-country option. It has no `locations` row: the
 * server resolves it in `services/job_search.py` (`_UNITED_STATES_OPTION`) and
 * the client in `jobFilteringUtils.resolveSelectedDescriptor`. It matches every
 * on-site US job, not remote ones.
 */
export const UNITED_STATES_OPTION = 'United States';

/**
 * The six places offered before the search: the most common primary job
 * locations in production (2026-11-22), then Remote (US) and the whole
 * country. Canonical names, exactly as the Location filter stores them.
 */
export const LOCATION_PRESETS: readonly string[] = [
  'San Francisco, CA, US',
  'New York, NY, US',
  'Seattle, WA, US',
  'Austin, TX, US',
  'Remote (US)',
  UNITED_STATES_OPTION,
];

/** A place as the chips show it: a US city drops its trailing ", US". */
export function displayPlace(canonicalName: string): string {
  return canonicalName.replace(/, US$/, '');
}

export const EMPTY_ANSWERS: OnboardingAnswers = {
  category: [],
  subcategory: [],
  level: [],
  locations: [],
  companyCategory: [],
};

/**
 * The answers as the request sends them. A specialty refines Software
 * Engineering, so it goes out only with Software Engineering picked (the
 * server enforces the same rule).
 */
export function toRequestAnswers(draft: OnboardingAnswers): OnboardingAnswers {
  return {
    category: [...draft.category],
    subcategory: draft.category.includes(SUBCATEGORY_PARENT_SLUG) ? [...draft.subcategory] : [],
    level: [...draft.level],
    locations: [...draft.locations],
    companyCategory: [...(draft.companyCategory ?? [])],
  };
}

/**
 * The body as an older backend accepts it, for the deploy window. That backend
 * 422s an unknown key and any `step` past 3, so the company types are left out
 * and the step is clamped. Whether the backend knows the field is read from the
 * saved-filters GET (`companyCategory` present), never from facets, which are
 * edge-cached.
 */
export function forBackend(
  body: CompleteOnboardingArgs,
  backendKnowsCompanyType: boolean
): CompleteOnboardingArgs {
  if (backendKnowsCompanyType) return body;
  const legacy: CompleteOnboardingArgs = { ...body, step: Math.min(body.step, 3) as 1 | 2 | 3 };
  delete legacy.companyCategory;
  return legacy;
}

/** Whether one question has an answer (for the `onboarding_step_completed` event). */
export function stepHasAnswer(draft: OnboardingAnswers, step: OnboardingStep): boolean {
  if (step === 0) return draft.category.length > 0;
  if (step === 1) return draft.level.length > 0;
  if (step === 2) return draft.locations.length > 0;
  return (draft.companyCategory?.length ?? 0) > 0;
}

/** Whether the saved filters carry any onboarding answer (decides the toast). */
export function savedFiltersHaveAnswers(saved: SavedFilters): boolean {
  return (
    saved.category.length > 0 ||
    saved.subcategory.length > 0 ||
    saved.level.length > 0 ||
    saved.locations.length > 0 ||
    (saved.companyCategory?.length ?? 0) > 0
  );
}

/** Add or remove one value, keeping the others in order. */
export function toggleValue(values: string[], value: string, on: boolean): string[] {
  if (on) return values.includes(value) ? values : [...values, value];
  return values.filter((v) => v !== value);
}

/**
 * Paths the questions never open on. Both render outside `RootLayout` today
 * (so the gate is not even mounted there); the check keeps that true if one
 * moves inside it. `/` is the signed-out landing page, and `/pricing` must stay
 * clear so a Stripe Checkout return is never interrupted.
 */
const ONBOARDING_EXCLUDED_PATHS: ReadonlySet<string> = new Set([ROUTES.HOME, ROUTES.PRICING]);

export function isOnboardingExcludedPath(pathname: string): boolean {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  return ONBOARDING_EXCLUDED_PATHS.has(normalized || '/');
}

/** What a screen reader hears once the questions close with answers saved. */
export const SAVED_FILTERS_ANNOUNCEMENT = 'Saved as your filters.';

export const ONBOARDING_SAVE_ERROR = 'Your answers could not be saved. Try again.';
