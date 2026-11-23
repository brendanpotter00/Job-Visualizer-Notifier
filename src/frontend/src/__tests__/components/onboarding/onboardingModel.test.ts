import { describe, it, expect } from 'vitest';
import {
  EMPTY_ANSWERS,
  LOCATION_PRESETS,
  displayPlace,
  isOnboardingExcludedPath,
  onboardingDocumentTitle,
  savedFiltersHaveAnswers,
  stepHasAnswer,
  toRequestAnswers,
  toggleValue,
} from '../../../components/onboarding/onboardingModel';
import { validateOnboardingResult } from '../../../features/savedFilters/savedFiltersApi';
import type { SavedFilters } from '../../../types';

const SAVED: SavedFilters = {
  recentTimeWindow: 'all',
  trendTimeWindow: '90d',
  locations: [],
  category: [],
  level: [],
  subcategory: [],
  recentActiveKeywordListId: null,
  trendActiveKeywordListId: null,
};

describe('onboardingModel', () => {
  it('offers the six preset places as canonical names, shown without ", US"', () => {
    expect(LOCATION_PRESETS).toEqual([
      'San Francisco, CA, US',
      'New York, NY, US',
      'Seattle, WA, US',
      'Austin, TX, US',
      'Remote (US)',
      'United States',
    ]);
    expect(LOCATION_PRESETS.map(displayPlace)).toEqual([
      'San Francisco, CA',
      'New York, NY',
      'Seattle, WA',
      'Austin, TX',
      'Remote (US)',
      'United States',
    ]);
    // Only a trailing ", US" goes; other countries keep theirs.
    expect(displayPlace('Toronto, ON, CA')).toBe('Toronto, ON, CA');
  });

  it('sends specialties only with Software Engineering picked', () => {
    expect(
      toRequestAnswers({ ...EMPTY_ANSWERS, category: ['growth'], subcategory: ['backend'] })
        .subcategory
    ).toEqual([]);
    expect(
      toRequestAnswers({
        ...EMPTY_ANSWERS,
        category: ['software_engineering', 'growth'],
        subcategory: ['backend'],
      }).subcategory
    ).toEqual(['backend']);
  });

  it('excludes / and /pricing, and nothing else', () => {
    expect(isOnboardingExcludedPath('/')).toBe(true);
    expect(isOnboardingExcludedPath('/pricing')).toBe(true);
    expect(isOnboardingExcludedPath('/pricing/')).toBe(true);
    expect(isOnboardingExcludedPath('/jobs')).toBe(false);
    expect(isOnboardingExcludedPath('/saved-filters')).toBe(false);
    expect(isOnboardingExcludedPath('/pricing-old')).toBe(false);
  });

  it('names each step in the tab title', () => {
    expect(onboardingDocumentTitle(0, 'onesecondswe')).toBe('Question 1 of 3: Roles | onesecondswe');
    expect(onboardingDocumentTitle(2, 'onesecondswe')).toBe('Question 3 of 3: Places | onesecondswe');
  });

  it('knows whether a step or the saved filters carry an answer', () => {
    const draft = { ...EMPTY_ANSWERS, level: ['mid'] };
    expect(stepHasAnswer(draft, 0)).toBe(false);
    expect(stepHasAnswer(draft, 1)).toBe(true);
    expect(stepHasAnswer(draft, 2)).toBe(false);
    expect(savedFiltersHaveAnswers(SAVED)).toBe(false);
    expect(savedFiltersHaveAnswers({ ...SAVED, locations: ['Remote (US)'] })).toBe(true);
  });

  it('toggles a value without duplicating it', () => {
    expect(toggleValue(['a'], 'b', true)).toEqual(['a', 'b']);
    expect(toggleValue(['a', 'b'], 'b', true)).toEqual(['a', 'b']);
    expect(toggleValue(['a', 'b'], 'a', false)).toEqual(['b']);
  });
});

describe('validateOnboardingResult', () => {
  it('accepts the server answer and normalizes its saved filters', () => {
    const { subcategory: _omitted, ...legacy } = SAVED;
    const result = validateOnboardingResult({
      onboardingCompletedAt: '2026-11-22T10:00:00+00:00',
      savedFilters: legacy,
    });
    expect(result.onboardingCompletedAt).toBe('2026-11-22T10:00:00+00:00');
    expect(result.savedFilters.subcategory).toEqual([]);
  });

  it('rejects a body without a stamp or with malformed saved filters', () => {
    expect(() => validateOnboardingResult({ savedFilters: SAVED })).toThrow(/onboardingCompletedAt/);
    expect(() =>
      validateOnboardingResult({ onboardingCompletedAt: 'x', savedFilters: { ...SAVED, level: 'mid' } })
    ).toThrow(/level/);
    expect(() => validateOnboardingResult(null)).toThrow(/not an object/);
  });
});
